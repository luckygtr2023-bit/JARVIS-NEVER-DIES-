"""Behavioural tests for the J.A.R.V.I.S. reasoning / research pipeline.

These are behaviour tests, not existence tests: they run the real
``agent.reasoner.ReasoningPipeline``, ``agent.intent`` classifier and
``agent.research`` browser-session orchestration with fake IO adapters
(fake search provider, fake browser session, fake AI) so each required
scenario is verified end to end without network or a real browser.

Scenarios covered (task spec):
  1. basic factual question
  2. multi-step reasoning question
  3. comparison question
  4. why/how question
  5. knowledge question that should NOT invoke browser/search
  6. explicit web research request
  7. "Open Brave and search for X"
  8. search + summarize
  9. search + reasoning
 10. multi-step compound command (open browser, search, summarize, advise)
 11. browser failure (honest fallback, no fake claims)
 12. search timeout
 13. empty search results
 14. AI backend unavailable
 15. OmniRoute unavailable (surfaced honestly)
 16. existing browser session (repeated searches keep working)
 17. invalid/unrecognized intent
 18. tool execution failure
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.intent import IntentKind, classify_intent  # noqa: E402
from agent.reasoner import (  # noqa: E402
    AIUnavailable,
    PipelineResult,
    ReasoningPipeline,
)
from agent.research import (  # noqa: E402
    BrowserResearchSession,
    ResearchReport,
    SourceResult,
)


# ── fakes ───────────────────────────────────────────────────────────────────

class FakeAI:
    """Records calls and returns scripted answers / errors."""

    def __init__(self, direct_answer="direct answer", reasoned_answer="reasoned answer",
                 direct_error=None, reasoned_error=None):
        self.direct_answer = direct_answer
        self.reasoned_answer = reasoned_answer
        self.direct_error = direct_error
        self.reasoned_error = reasoned_error
        self.direct_calls = []
        self.reasoned_calls = []

    def direct(self, question, memory_ctx=""):
        self.direct_calls.append((question, memory_ctx))
        if self.direct_error:
            raise self.direct_error
        return self.direct_answer

    def reasoned(self, question, memory_ctx="", evidence=None):
        self.reasoned_calls.append((question, memory_ctx, evidence))
        if self.reasoned_error:
            raise self.reasoned_error
        return self.reasoned_answer


class FakeSearchProvider:
    """Search provider adapter standing in for agent.research.search_web."""

    def __init__(self, report=None, error=None):
        self.report = report
        self.error = error
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        if self.report is not None:
            r = self.report
            return ResearchReport(
                ok=r.get("ok", True), query=query,
                method=r.get("method", "duckduckgo"),
                status=r.get("status", "ok"),
                results=r.get("results", []),
                raw_text=r.get("raw_text", ""),
                error=r.get("error"),
                warnings=list(r.get("warnings", [])),
                phases=r.get("phases", ["results loaded"]),
            )
        return ResearchReport(
            ok=True, query=query, method="duckduckgo", status="ok",
            results=[SourceResult(
                title="Mitochondrion - Wikipedia",
                snippet="Mitochondria are membrane-bound organelles that generate most "
                        "of the cell's supply of chemical energy.",
                url="https://en.wikipedia.org/wiki/Mitochondrion",
                rank=1,
            )],
            phases=["results loaded (1 retrieved)"],
        )


def ok_report(query, title="Retrieved Title", snippet="Retrieved snippet body text.",
              url="https://example.com/a"):
    return {
        "ok": True, "method": "duckduckgo", "status": "ok",
        "results": [SourceResult(title=title, snippet=snippet, url=url, rank=1)],
        "phases": ["results loaded (1 retrieved)"],
    }


class FakeBrowserSession:
    """Stands in for BrowserResearchSession (same public API)."""

    def __init__(self, mode="ok"):
        self.mode = mode
        self.search_calls = []
        self.open_calls = []

    def search(self, query, browser="brave"):
        self.search_calls.append((query, browser))
        if self.mode == "launch_error":
            return ResearchReport(
                ok=False, query=query, method="browser", status="error",
                error="Browser search failed: launch exploded",
                phases=["browser action requested", "browser search failed (launch exploded)"],
            )
        if self.mode == "extract_empty":
            return ResearchReport(
                ok=True, query=query, method="browser", status="empty",
                results=[], raw_text="", warnings=["no parseable results"],
                phases=["extraction failed - no parseable results"],
            )
        return ResearchReport(
            ok=True, query=query, method="browser", status="ok",
            results=[SourceResult(
                title="Mitochondrion - Wikipedia",
                snippet="Mitochondria are membrane-bound organelles that generate most "
                        "of the cell's supply of chemical energy.",
                url="https://en.wikipedia.org/wiki/Mitochondrion",
                rank=1,
            )],
            phases=[
                "browser launched", "search submitted", "results loaded",
                "extraction succeeded (1 results)",
            ],
        )


class CommandRunner:
    def __init__(self, result="ran action", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, intent):
        self.calls.append(intent)
        if self.error:
            raise self.error
        return self.result


def make_pipeline(ai=None, search=None, browser=None):
    return ReasoningPipeline(
        ai=ai or FakeAI(),
        search_fn=(search.search if search else None),
        browser=browser,
        log=lambda msg: None,
    )


# ── 1–5: direct questions never touch tools ─────────────────────────────────

def test_basic_factual_question():
    ai = FakeAI(direct_answer="A mitochondrion is the cell's powerhouse.")
    search = FakeSearchProvider()
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle("What is a mitochondrion?")
    assert result.intent.kind == IntentKind.ANSWER_KNOWLEDGE
    assert result.answer == "A mitochondrion is the cell's powerhouse."
    assert ai.direct_calls and ai.direct_calls[0][0] == "What is a mitochondrion?"
    assert search.calls == []  # no search performed
    assert result.web_used is False


def test_multi_step_reasoning_question():
    ai = FakeAI()
    search = FakeSearchProvider()
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle(
        "A 2 kg block slides on a frictionless surface at 4 m/s. "
        "How much force is needed to stop it in 2 seconds?"
    )
    assert result.intent.kind == IntentKind.REASONING
    assert ai.reasoned_calls and ai.reasoned_calls[0][2] is None  # no evidence
    assert search.calls == []
    assert result.answer == "reasoned answer"


def test_comparison_question():
    ai = FakeAI()
    search = FakeSearchProvider()
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle("Compare RTX 4060 and 4070 for 1440p gaming and explain the tradeoffs.")
    assert result.intent.kind == IntentKind.REASONING
    assert ai.reasoned_calls
    assert search.calls == []


def test_why_how_question():
    ai = FakeAI()
    search = FakeSearchProvider()
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle("Why does increasing resistance reduce current?")
    assert result.intent.kind == IntentKind.REASONING
    assert ai.reasoned_calls and search.calls == []


def test_knowledge_question_does_not_invoke_browser():
    browser = FakeBrowserSession()
    ai = FakeAI()
    search = FakeSearchProvider()
    pipe = make_pipeline(ai=ai, search=search, browser=browser)
    result = pipe.handle("Explain what photosynthesis is in simple terms.")
    assert result.intent.kind == IntentKind.ANSWER_KNOWLEDGE
    assert browser.search_calls == [] and search.calls == []
    assert result.answer == "direct answer"


# ── 6: explicit web research ────────────────────────────────────────────────

def test_explicit_web_research_request():
    ai = FakeAI()
    search = FakeSearchProvider(report=ok_report("latest paper news",
                                                 title="Paper 1.21 Released",
                                                 snippet="Paper 1.21 adds the new creator tools."))
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle(
        "Search the web for the latest Minecraft Paper server changes and explain what matters for my server."
    )
    assert result.intent.kind == IntentKind.WEB_RESEARCH
    assert result.intent.query == "the latest Minecraft Paper server changes"
    assert search.calls == ["the latest Minecraft Paper server changes"]
    assert result.web_used is True
    assert result.sources and result.sources[0].title == "Paper 1.21 Released"
    assert ai.reasoned_calls
    _, _, evidence = ai.reasoned_calls[0]
    assert evidence and "RETRIEVED FACTS" in evidence and "Paper 1.21 Released" in evidence


# ── 7: open Brave and search ────────────────────────────────────────────────

def test_open_brave_and_search():
    browser = FakeBrowserSession(mode="ok")
    ai = FakeAI()
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider(), browser=browser)
    result = pipe.handle("Open Brave and search for what is mitochondria.")
    assert result.intent.kind == IntentKind.BROWSER_SEARCH
    assert result.intent.browser == "brave"
    assert result.intent.query == "mitochondria"
    assert browser.search_calls == [("mitochondria", "brave")]
    assert any("browser launched" in p for p in result.trace)
    assert any("search submitted" in p for p in result.trace)
    assert any("extraction succeeded" in p for p in result.trace)
    assert result.web_used is True
    assert result.sources and "Mitochondria are membrane-bound" in result.sources[0].snippet
    assert ai.reasoned_calls  # synthesis step happened after extraction


# ── 8: search + summarize ───────────────────────────────────────────────────

def test_search_and_summarize():
    ai = FakeAI()
    search = FakeSearchProvider(report=ok_report("weather", "Sunny 24C",
                                                 "Clear skies with a high near 24 degrees."))
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle("Search the web for today's weather in Berlin and summarize it for me.")
    assert result.intent.kind == IntentKind.WEB_RESEARCH
    assert search.calls and "weather" in search.calls[0]
    assert ai.reasoned_calls and "Sunny 24C" in (ai.reasoned_calls[0][2] or "")
    assert result.answer


# ── 9: search + reasoning ───────────────────────────────────────────────────

def test_search_and_reasoning():
    ai = FakeAI()
    search = FakeSearchProvider(report=ok_report("q", "Key Finding",
                                                 "The new release changes world generation."))
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle(
        "Search the web for recent changes in world generation and reason about what "
        "they mean for my survival server."
    )
    assert result.intent.kind == IntentKind.WEB_RESEARCH
    assert ai.reasoned_calls and "Key Finding" in (ai.reasoned_calls[0][2] or "")


# ── 10: multi-step compound command ─────────────────────────────────────────

def test_compound_open_search_summarize_advise():
    browser = FakeBrowserSession(mode="ok")
    ai = FakeAI()
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider(), browser=browser)
    result = pipe.handle(
        "open my browser, search for the weather, summarize the result, and tell me "
        "what I should prepare for"
    )
    assert result.intent.kind == IntentKind.BROWSER_SEARCH
    assert result.intent.query == "the weather"
    assert browser.search_calls == [("the weather", "browser")]
    # The compound request must not stop at opening: a search ran and the
    # evidence was fed into synthesis.
    assert any("search submitted" in p for p in result.trace)
    assert ai.reasoned_calls
    assert result.answer


# ── 11: browser failure -> honest fallback ──────────────────────────────────

def test_browser_failure_falls_back_honestly():
    browser = FakeBrowserSession(mode="launch_error")
    ai = FakeAI()
    search = FakeSearchProvider(report=ok_report("mitochondria",
                                                 title="Wiki Mitochondrion",
                                                 snippet="Wikipedia overview of mitochondria."))
    pipe = make_pipeline(ai=ai, search=search, browser=browser)
    result = pipe.handle("Open Brave and search for mitochondria.")
    assert result.intent.kind == IntentKind.BROWSER_SEARCH
    # The fallback search ran and its results were used:
    assert search.calls == ["mitochondria"]
    assert result.sources and result.sources[0].title == "Wiki Mitochondrion"
    assert ai.reasoned_calls
    # Honesty markers: browser failure is reported and the DuckDuckGo fallback
    # is visible in the trace (no fake claim that the browser search worked).
    assert any("browser search failed" in p for p in result.trace)
    assert any("fallback" in p.lower() for p in result.trace)


def test_browser_failure_and_search_failure_is_honest():
    browser = FakeBrowserSession(mode="launch_error")
    ai = FakeAI()
    search = FakeSearchProvider(report={"ok": False, "method": "none", "status": "error",
                                        "error": "All search providers failed: DuckDuckGo: net down; Gemini: no key",
                                        "results": [], "phases": ["all search providers failed"]})
    pipe = make_pipeline(ai=ai, search=search, browser=browser)
    result = pipe.handle("Open Brave and search for mitochondria.")
    assert result.ok is False
    assert "could not complete that web research" in result.answer
    assert "launch exploded" in result.error
    assert "All search providers failed" in result.error
    assert ai.reasoned_calls == []  # never fabricates an answer


# ── 12: search timeout ──────────────────────────────────────────────────────

def test_search_timeout_is_reported_honestly():
    ai = FakeAI()
    search = FakeSearchProvider(report={"ok": False, "method": "none", "status": "timeout",
                                        "error": "SEARCH TIMEOUT - DuckDuckGo: slow",
                                        "results": [], "phases": ["search timed out"]})
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle("Search the web for the price of Bitcoin right now.")
    assert result.ok is False
    assert "timed out" in result.answer.lower()
    assert "SEARCH TIMEOUT" in result.error
    assert ai.reasoned_calls == []  # nothing retrieved -> nothing invented


# ── 13: empty search results ────────────────────────────────────────────────

def test_empty_search_results_reported():
    ai = FakeAI()
    search = FakeSearchProvider(report={"ok": True, "method": "duckduckgo", "status": "empty",
                                        "results": [], "raw_text": "",
                                        "phases": ["no results"]})
    pipe = make_pipeline(ai=ai, search=search)
    result = pipe.handle("Search the web for zzqx no such thing exists")
    assert "no results were retrieved" in result.answer.lower()
    assert ai.reasoned_calls == []
    assert ai.direct_calls == []


# ── 14: AI backend unavailable ──────────────────────────────────────────────

def test_ai_backend_unavailable():
    ai = FakeAI(direct_error=AIUnavailable("AI UNAVAILABLE - Local: down; OmniRoute: down; OpenRouter: 401"))
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider())
    result = pipe.handle("What is a mitochondrion?")
    assert result.ok is False
    assert "AI UNAVAILABLE" in result.error
    assert "could not reach any ai provider" in result.answer.lower()


# ── 15: OmniRoute unavailable ───────────────────────────────────────────────

def test_omniroute_unavailable_surfaced():
    ai = FakeAI(direct_error=AIUnavailable("OMNIROUTE UNAVAILABLE - http://localhost:20128/chat/completions refused"))
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider())
    result = pipe.handle("What is a mitochondrion?")
    assert result.ok is False
    assert "OMNIROUTE UNAVAILABLE" in result.error
    assert result.answer  # honest message, no fabricated success


# ── 16: existing browser session (repeated searches) ────────────────────────

def test_existing_browser_session_reuses_flow():
    browser = FakeBrowserSession(mode="ok")
    ai = FakeAI(reasoned_answer="First answer.")
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider(), browser=browser)
    r1 = pipe.handle("Open Brave and search for mitochondria")
    ai.reasoned_answer = "Second answer."
    r2 = pipe.handle("now search for ribosomes in the same browser")
    assert r1.intent.kind == IntentKind.BROWSER_SEARCH
    assert r2.intent.kind == IntentKind.BROWSER_SEARCH
    # Both requests actually ran searches and produced grounded answers.
    assert browser.search_calls[0][0] == "mitochondria"
    assert browser.search_calls[1][0] == "ribosomes"
    assert len(ai.reasoned_calls) == 2


# ── 17: invalid/unrecognized intent ─────────────────────────────────────────

def test_unrecognized_intent_routes_to_direct_answer():
    ai = FakeAI(direct_answer="I am not sure what that means, sir.")
    search = FakeSearchProvider()
    browser = FakeBrowserSession()
    pipe = make_pipeline(ai=ai, search=search, browser=browser)
    result = pipe.handle("zzqx flurbity bloop")
    assert result.intent.kind == IntentKind.UNKNOWN
    assert ai.direct_calls
    assert search.calls == [] and browser.search_calls == []
    assert result.answer == "I am not sure what that means, sir."


# ── 18: tool execution failure ──────────────────────────────────────────────

def test_tool_execution_failure_honest():
    ai = FakeAI()
    runner = CommandRunner(error=RuntimeError("open_app could not find Spotify"))
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider())
    result = pipe.handle("open spotify", command_runner=runner)
    assert result.intent.kind == IntentKind.OPEN_APP
    assert result.ok is False
    assert "Action execution failed" in result.error
    assert "could not complete that action" in result.answer.lower()


def test_open_app_command_runs_through_runner():
    ai = FakeAI()
    runner = CommandRunner(result="Opened Brave successfully, sir.")
    pipe = make_pipeline(ai=ai, search=FakeSearchProvider())
    result = pipe.handle("open brave", command_runner=runner)
    assert result.intent.kind == IntentKind.OPEN_APP
    assert result.answer == "Opened Brave successfully, sir."
    assert runner.calls and runner.calls[0].app_name.lower() == "brave"


# ── classifier robustness (pure) ────────────────────────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("What is a mitochondrion?", IntentKind.ANSWER_KNOWLEDGE),
    ("Why does increasing resistance reduce current?", IntentKind.REASONING),
    ("Compare these two approaches and explain the tradeoffs.", IntentKind.REASONING),
    ("Which laptop setup would be better for this workload and why?", IntentKind.REASONING),
    ("search the web for the latest information about X", IntentKind.WEB_RESEARCH),
    ("Open Brave and search for what is mitochondria", IntentKind.BROWSER_SEARCH),
    ("open my browser, search for the weather, summarize it", IntentKind.BROWSER_SEARCH),
    ("open spotify", IntentKind.OPEN_APP),
])
def test_classifier_kinds(text, kind):
    assert classify_intent(text).kind == kind


def test_browser_search_query_extraction():
    intent = classify_intent("Open Brave and search for what is mitochondria")
    assert intent.query == "mitochondria"
    intent2 = classify_intent(
        "open my browser, search for the weather, summarize the result, and tell "
        "me what I should prepare for"
    )
    assert intent2.query == "the weather"
