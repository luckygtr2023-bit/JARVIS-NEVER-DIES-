"""J.A.R.V.I.S. reasoning / intent pipeline.

Conceptual flow for every user request:

    USER INPUT
       -> intent understanding        (agent.intent.classify_intent)
       -> task classification         (question vs research vs action)
       -> plan / decomposition        (agent.intent.plan_for)
       -> tool selection & execution  (search_web / BrowserResearchSession /
                                       host command_runner)
       -> result collection
       -> reasoning / synthesis       (AI chain, evidence-grounded when web used)
       -> final answer

Key guarantees:
- Normal knowledge questions are answered directly — they are never turned
  into shell commands or forced searches.
- Reasoning questions go to the AI with a reasoning frame, not a shallow
  keyword echo.
- Web research requests always run a real search and the final answer is
  grounded in retrieved facts (or says plainly that nothing was retrieved).
- "Open <browser> and search for X" runs the full open -> search -> extract
  -> synthesize sequence and never stops after opening the browser.
- When a provider fails, the failure is reported honestly. Nothing is faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agent.intent import Intent, IntentKind, classify_intent, plan_for
from agent.research import (
    BrowserResearchSession,
    ResearchReport,
    SourceResult,
    format_evidence,
    search_web,
)


class AIUnavailable(RuntimeError):
    """Every configured AI provider failed — raised with honest details."""


# ── default AI provider (existing J.A.R.V.I.S. chain) ───────────────────────

class UnifiedChainAI:
    """AI adapter over the existing routing chain.

    Tries, in order:
      1. Google Gemini text reply (existing ``_gemini_text_reply`` path)
      2. ``llm_client.client`` — the existing UnifiedAIClient chain
         (Local Ollama -> OmniRoute -> OpenRouter/Gemini)

    Exactly mirrors the app's current fallback order; nothing is replaced or
    duplicated, this is just the same chain surfaced through one interface so
    the pipeline can call it consistently.
    """

    def __init__(self, gemini_first: bool = True, log: Optional[Callable[[str], None]] = None):
        self._gemini_first = gemini_first
        self._log = log or (lambda msg: print(f"[Reasoner-AI] {msg}"))

    @staticmethod
    def _gemini_text(prompt: str) -> str:
        """Call the app's existing Gemini text helper without double-importing
        main.py (which runs as __main__ when launched via `python main.py`)."""
        import sys
        mod = sys.modules.get("main") or sys.modules.get("__main__")
        fn = getattr(mod, "_gemini_text_reply", None) if mod else None
        if fn is None:
            raise RuntimeError("Gemini text helper is not available in this context")
        return fn(prompt)

    @staticmethod
    def _unified_chat(prompt: str, system: str) -> str:
        from llm_client import client as unified
        return unified.chat(prompt, system=system)

    def _answer(self, prompt: str, system: str) -> str:
        errors: list[str] = []
        providers: list[tuple[str, Callable[[], str]]] = []
        if self._gemini_first:
            providers.append(("Gemini", lambda: self._gemini_text(prompt)))
            providers.append(("Local->OmniRoute->OpenRouter", lambda: self._unified_chat(prompt, system)))
        else:
            providers.append(("Local->OmniRoute->OpenRouter", lambda: self._unified_chat(prompt, system)))
            providers.append(("Gemini", lambda: self._gemini_text(prompt)))
        for label, fn in providers:
            try:
                result = (fn() or "").strip()
                if result:
                    return result
                errors.append(f"{label} returned an empty response")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc}")
                self._log(f"{label} failed ({exc})")
        detail = "; ".join(errors) if errors else "No AI provider responded."
        raise AIUnavailable(f"AI UNAVAILABLE - {detail}")

    def direct(self, question: str, memory_ctx: str = "") -> str:
        ctx = f"{memory_ctx}\n\n" if memory_ctx else ""
        system = (
            "You are J.A.R.V.I.S. ('Just A Rather Very Intelligent System'). "
            "Answer the user's question directly, accurately, and concisely. "
            "If you are not certain, say so. Never claim to have searched the "
            "web or run tools when you have not."
        )
        return self._answer(f"{ctx}{question}", system)

    def reasoned(self, question: str, memory_ctx: str = "",
                 evidence: Optional[str] = None) -> str:
        ctx = f"{memory_ctx}\n\n" if memory_ctx else ""
        if evidence:
            system = (
                "You are J.A.R.V.I.S. ('Just A Rather Very Intelligent System'). "
                "Reason carefully through the user's request. Ground your answer "
                "in the RETRIEVED FACTS provided below. Clearly distinguish what "
                "was retrieved from what is your own inference, and flag any "
                "uncertainty or missing information."
            )
            return self._answer(f"{evidence}\n\n{ctx}USER REQUEST:\n{question}", system)
        system = (
            "You are J.A.R.V.I.S. ('Just A Rather Very Intelligent System'). "
            "The user is asking a reasoning question (why/how/compare/trade-offs). "
            "Work through the actual reasoning step by step, compare the real "
            "factors involved, and give a clear, structured conclusion. Do not "
            "echo keywords back at the user; think and then answer."
        )
        return self._answer(f"{ctx}{question}", system)


# ── pipeline result & runner ────────────────────────────────────────────────

@dataclass
class PipelineResult:
    intent: Intent
    answer: str = ""
    ok: bool = True
    deferred_action: bool = False
    web_used: bool = False
    trace: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    error: Optional[str] = None

    def render_trace(self) -> str:
        return "\n".join(self.trace)


class ReasoningPipeline:
    """Orchestrates intent -> plan -> execution -> synthesis for one request.

    Everything is injectable for behavioural tests:
      - ``ai``           : object with direct()/reasoned() (default: real chain)
      - ``search_fn``    : (query) -> ResearchReport (default: real search_web)
      - ``browser``      : BrowserResearchSession (default: real browser glue)
      - ``command_runner``: callable(intent) -> Optional[str] that the host
                            provides to actually execute OPEN_APP / ACTION
                            requests with the app's own action dispatcher.
    """

    def __init__(
        self,
        ai: Optional[object] = None,
        search_fn: Optional[Callable[[str], ResearchReport]] = None,
        browser: Optional[BrowserResearchSession] = None,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.ai = ai if ai is not None else UnifiedChainAI()
        self._search_fn = search_fn or search_web
        self._browser = browser if browser is not None else BrowserResearchSession()
        self._log = log or (lambda msg: print(f"[Reasoner] {msg}"))

    # -- trace ------------------------------------------------------------

    def _trace(self, msg: str) -> None:
        self._log(msg)

    # -- execution ---------------------------------------------------------

    def handle(
        self,
        text: str,
        memory_ctx: str = "",
        command_runner: Optional[Callable[[Intent], Optional[str]]] = None,
    ) -> PipelineResult:
        intent = classify_intent(text)
        result = PipelineResult(intent=intent)
        emit = result.trace.append
        emit(f"intent detected: {intent.describe()}")
        self._trace(f"intent detected: {intent.describe()}")

        # Direct-answer kinds (never touch tools/browser).
        if intent.kind in (IntentKind.ANSWER_KNOWLEDGE, IntentKind.CHITCHAT,
                           IntentKind.UNKNOWN):
            emit("reasoning started: direct answer path (no tools)")
            try:
                result.answer = self.ai.direct(text, memory_ctx)
                emit("final answer generated")
                return self._finish(result)
            except AIUnavailable as exc:
                return self._ai_down(result, exc, intent)

        if intent.kind == IntentKind.REASONING:
            emit("reasoning started: reasoning question (no tools)")
            try:
                result.answer = self.ai.reasoned(text, memory_ctx)
                emit("final answer generated")
                return self._finish(result)
            except AIUnavailable as exc:
                return self._ai_down(result, exc, intent)

        # Action kinds: ask the host to run the real action.
        if intent.kind in (IntentKind.OPEN_APP, IntentKind.ACTION_COMMAND):
            if command_runner is None:
                result.deferred_action = True
                result.answer = ""
                emit("action request deferred to host dispatcher")
                return self._finish(result)
            try:
                emit("action execution started")
                out = command_runner(intent)
                result.answer = out or ""
                emit("action execution finished")
                return self._finish(result)
            except Exception as exc:  # noqa: BLE001
                result.ok = False
                result.error = f"Action execution failed: {exc}"
                result.answer = (
                    "I could not complete that action, sir. "
                    f"Details: {exc}"
                )
                emit("action execution failed")
                return self._finish(result)

        # Web research: real search, then evidence-grounded synthesis.
        if intent.kind == IntentKind.WEB_RESEARCH:
            result.web_used = True
            emit(f"web research requested: '{intent.query}'")
            report = self._search_fn(intent.query)
            result.sources = list(report.results)
            for phase in report.phases:
                emit(f"search: {phase}")
            return self._finish_web(result, report, text, memory_ctx)

        # Browser search: full open -> search -> extract -> synthesize.
        if intent.kind == IntentKind.BROWSER_SEARCH:
            result.web_used = True
            browser_name = intent.browser or "brave"
            emit(f"browser search requested: {browser_name} for '{intent.query}'")
            self._trace("browser action requested")
            report = self._browser.search(intent.query, browser=browser_name)
            for phase in report.phases:
                emit(f"browser: {phase}")
            result.sources = list(report.results)
            if report.ok and report.results:
                return self._finish_web(result, report, text, memory_ctx)
            # Browser path failed or returned nothing -> honest fallback to the
            # API search path (never a fake claim of a browser search).
            emit("browser path did not yield results; trying DuckDuckGo fallback")
            self._trace("browser extraction failed - using search fallback")
            report2 = self._search_fn(intent.query)
            for phase in report2.phases:
                emit(f"fallback search: {phase}")
            if report2.ok and (report2.results or report2.raw_text):
                report2.warnings.insert(
                    0,
                    f"Browser ({browser_name}) search produced no parseable "
                    "results; the answer below is grounded in a DuckDuckGo "
                    "search instead.",
                )
                result.sources = list(report2.results)
                return self._finish_web(result, report2, text, memory_ctx)
            # Everything failed or empty — honest, no hallucination.
            browser_detail = report.error or "no parseable browser results"
            search_detail = report2.error or "no results"
            result.ok = False
            result.error = f"{browser_detail}; {search_detail}"
            result.answer = (
                f"I could not complete that web research, sir. "
                f"Browser search failed ({browser_detail}) and the fallback "
                f"search also failed ({search_detail})."
            )
            emit("final answer generated (honest failure report)")
            return self._finish(result)

        # Should not happen — every IntentKind is handled above.
        result.ok = False
        result.error = f"Unhandled intent kind: {intent.kind}"
        result.answer = "I did not understand how to route that request, sir."
        return self._finish(result)

    # -- shared helpers ------------------------------------------------------

    def _finish_web(self, result: PipelineResult, report: ResearchReport,
                    text: str, memory_ctx: str) -> PipelineResult:
        emit = result.trace.append
        if report.status == "timeout":
            result.ok = False
            result.error = report.error or "search timed out"
            result.answer = (
                f"The web search for '{report.query}' timed out, sir. "
                "I did not retrieve any results, so I won't guess. Please try again."
            )
            emit("search timed out - no fabricated results")
            return result
        if report.status == "empty" or (report.ok and not report.results and not report.raw_text):
            result.answer = (
                f"I searched for '{report.query}' but no results were retrieved, sir. "
                "Try rephrasing your request or giving me more context."
            )
            emit("empty search results - reported honestly")
            return result
        if not report.ok:
            result.ok = False
            result.error = report.error or "search failed"
            result.answer = (
                f"The web search for '{report.query}' failed, sir. "
                f"{report.error} I won't invent results."
            )
            emit("search failed - reported honestly")
            return result
        # Success: synthesize grounded answer.
        emit("reasoning started: evidence-grounded synthesis")
        self._trace("reasoning started")
        evidence = format_evidence(report)
        try:
            result.answer = self.ai.reasoned(text, memory_ctx, evidence=evidence)
            emit("final answer generated")
            return result
        except AIUnavailable as exc:
            return self._ai_down(result, exc, result.intent)

    def _ai_down(self, result: PipelineResult, exc: Exception,
                 intent: Intent) -> PipelineResult:
        result.ok = False
        result.error = str(exc)
        result.answer = (
            "I could not reach any AI provider to form that answer, sir. "
            "Please check config/api_keys.json and that Ollama/OmniRoute are running."
        )
        result.trace.append("all AI providers failed - reported honestly")
        return self._finish(result)

    def _finish(self, result: PipelineResult) -> PipelineResult:
        return result


def run_pipeline(text: str, memory_ctx: str = "",
                 ai: Optional[object] = None,
                 search_fn: Optional[Callable[[str], ResearchReport]] = None,
                 browser: Optional[BrowserResearchSession] = None,
                 command_runner: Optional[Callable[[Intent], Optional[str]]] = None,
                 log: Optional[Callable[[str], None]] = None) -> PipelineResult:
    """Convenience entry point."""
    pipe = ReasoningPipeline(ai=ai, search_fn=search_fn, browser=browser, log=log)
    return pipe.handle(text, memory_ctx=memory_ctx, command_runner=command_runner)
