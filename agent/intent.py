"""J.A.R.V.I.S. intent understanding layer.

Deterministic, offline-first classification of a user request so the rest of
the pipeline can choose the correct path:

    ANSWER_KNOWLEDGE  -> direct AI answer (no tools)
    REASONING         -> direct AI answer framed for reasoning (no tools)
    WEB_RESEARCH      -> real web search, then synthesize from retrieved facts
    BROWSER_SEARCH    -> open a real browser, perform the search there, then
                         extract + synthesize
    OPEN_APP          -> launch an application
    ACTION_COMMAND    -> existing command/action routing (never questions)
    CHITCHAT          -> direct AI answer
    UNKNOWN           -> ask for clarification / direct AI answer

Design rules (enforced here so the model does not have to):
- A normal knowledge/reasoning question is NEVER turned into a shell command
  or into a forced web_search.
- A web research request is NEVER satisfied by merely opening a browser or by
  an ungrounded text reply.
- "Open <browser> and search for X" is decomposed into an ordered plan:
  open browser -> search -> extract results -> synthesize.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IntentKind(str, Enum):
    ANSWER_KNOWLEDGE = "ANSWER_KNOWLEDGE"
    REASONING = "REASONING"
    WEB_RESEARCH = "WEB_RESEARCH"
    BROWSER_SEARCH = "BROWSER_SEARCH"
    OPEN_APP = "OPEN_APP"
    ACTION_COMMAND = "ACTION_COMMAND"
    CHITCHAT = "CHITCHAT"
    UNKNOWN = "UNKNOWN"


@dataclass
class PlanStep:
    name: str
    description: str
    params: dict = field(default_factory=dict)
    critical: bool = True


@dataclass
class Intent:
    text: str
    kind: IntentKind
    query: str = ""
    browser: Optional[str] = None
    app_name: Optional[str] = None
    confidence: float = 0.5
    notes: list = field(default_factory=list)

    @property
    def needs_web(self) -> bool:
        return self.kind in (IntentKind.WEB_RESEARCH, IntentKind.BROWSER_SEARCH)

    @property
    def wants_browser(self) -> bool:
        return self.kind == IntentKind.BROWSER_SEARCH

    def describe(self) -> str:
        return (
            f"Intent(kind={self.kind.value}, query={self.query!r}, "
            f"browser={self.browser!r}, app={self.app_name!r})"
        )


# ── vocabulary ──────────────────────────────────────────────────────────────

_KNOWLEDGE_WORDS = (
    "what is", "what's", "whats", "who is", "who was", "define", "meaning",
    "definition", "what does", "explain what", "tell me about",
)

_REASONING_TRIGGERS = (
    "why", "how does", "how do", "how can", "how much", "how many", "compare",
    "tradeoff", "trade-off", "trade off", "which is better",
    "which would be better", "pros and cons", "advantages and disadvantages",
    "vs ", "versus", "reasoning", "explain why", "would you recommend",
    "should i", "what happens if", "what would happen", "calculate", "compute",
    "solve", "work out", "difference between", "what's the difference",
    "better for",
)

_WEB_RESEARCH_TRIGGERS = (
    "search the web", "search online", "search the internet", "look up online",
    "look it up on the web", "web search", "do a web search", "google it",
    "what is the latest", "latest news", "latest information", "breaking news",
    "current price", "price today", "stock price", "crypto price",
    "news about", "recent ", "right now", "as of today", "today's",
    "find out online", "research online", "up-to-date", "up to date",
)

_BROWSER_NAMES = ("brave", "chrome", "chromium", "firefox", "edge", "opera", "vivaldi", "safari")
_GENERIC_BROWSER_WORDS = ("browser", "internet", "web browser")

_QUESTION_PREFIXES = (
    "what", "what's", "whats", "who", "who's", "whos", "when", "where",
    "why", "how", "which", "is ", "are ", "can ", "could ", "would ",
    "should ", "does ", "do ", "explain", "define", "describe", "compare",
    "tell me", "give me", "name ", "list ",
)

# Known action verbs for ACTION_COMMAND detection (non-question commands).
_ACTION_VERBS = (
    "send ", "set ", "create ", "make ", "write ", "play ", "pause ", "stop ",
    "skip ", "shutdown", "restart", "remind", "take ", "screenshot",
    "turn on ", "turn off ", "close ", "delete ", "rename ", "move ",
    "copy ", "download ", "install ", "update ", "schedule ", "check ",
    "find ", "show ", "block ", "mute ", "unmute ", "increase ", "decrease ",
    "email ", "call ", "post ", "upload ",
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _find_browser(text: str) -> Optional[str]:
    low = text.lower()
    for name in _BROWSER_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return name
    for name in _GENERIC_BROWSER_WORDS:
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return name  # normalized to a real browser by callers when launching
    return None


def _looks_question(text: str) -> bool:
    low = text.lower().strip()
    if low.endswith("?"):
        return True
    if re.match(r"^(what|who|when|where|why|how|which|whose|whom)\b", low):
        return True
    if re.match(r"^(is|are|can|could|would|should|does|do|did|will)\b", low):
        return True
    for prefix in ("explain ", "define ", "describe ", "compare ", "tell me "):
        if low.startswith(prefix):
            return True
    return False


def _trim_trailing_clauses(query: str) -> str:
    """Keep only the core query before connectors like ', and tell me ...'."""
    parts = [part.strip() for part in query.split(",")]
    core = parts[0]
    low = core.lower()
    for marker in (
        " and then summarize", " and then tell me", " and summarize",
        " and tell me", " and then give", " then summarize", " and prepare",
        " and explain", " and why it matters", " please",
    ):
        idx = low.find(marker)
        if idx > 0:
            core = core[:idx]
    return core.strip(" '\".,!?")


def _strip_question_prefix(text: str) -> str:
    low = text.lower().strip()
    for prefix in (
        "can you tell me about ", "could you tell me about ",
        "can you tell me ", "could you tell me ",
        "tell me about ", "tell me ", "do you know ",
        "what is a ", "what is an ", "what is the ", "what is ",
        "what are ", "what's a ", "what's an ", "what's the ", "what's ",
        "whats a ", "whats an ", "whats the ", "whats ",
        "who is ", "who was ", "who's ", "whos ",
        "define ", "explain why ", "explain what ", "explain how ",
        "explain ", "describe ", "why is ", "why are ", "why does ",
        "why do ", "how does ", "how do ", "how can ", "what does ",
        "what do ", "compare ", "which is better ",
    ):
        if low.startswith(prefix):
            rest = text.strip()[len(prefix):].strip()
            return rest if rest else text.strip()
    return text.strip()


def _trim_web_prefix(text: str) -> str:
    """Strip 'search the web for / look up / google ...' command phrases."""
    low = text.lower().strip()
    for prefix in (
        "search the web for ", "search the web about ", "search the web ",
        "search online for ", "search online about ", "search online ",
        "search the internet for ", "search the internet ",
        "search for ", "search about ",
        "look up on the web ", "look it up on the web ", "look it up online ",
        "look up online ", "look up ", "web search for ", "web search ",
        "do a web search for ", "do a web search ",
        "find out online ", "research online ", "google ",
    ):
        if low.startswith(prefix):
            rest = text.strip()[len(prefix):].strip()
            return rest if rest else text.strip()
    return text.strip()


def _looks_browser_search(text: str) -> bool:
    """True for: 'open brave and search X', 'search X in chrome', 'open my
    browser, search for the weather ...' style compound requests."""
    low = text.lower()
    if _find_browser(low) is None:
        return False
    if not any(tok in low for tok in ("search", "look up", "find ", "google ")):
        return False
    if "search" in low:
        return True
    return False


# ── public API ──────────────────────────────────────────────────────────────

def extract_query_from_browser_search(text: str) -> str:
    """Pull 'X' out of 'open Brave and search for X' style requests."""
    low = text.lower()
    patterns = [
        r"\bsearch\s+(?:the\s+web\s+)?(?:for\s+|about\s+)?(.+?)\s+(?:in|on|using|with|via)\s+[\w ]+$",
        r"\bopen\s+\w[\w ]*\s*(?:and|,)?\s*search\s+(?:for|about)?\s*(.+)$",
        r"\bsearch\s+(?:for\s+|about\s+)?(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, low)
        if m and m.group(1).strip():
            q = m.group(1).strip(" '\".,!?")
            return _trim_trailing_clauses(_strip_question_prefix(q) or q)
    for marker in ("search for ", "search about ", "search "):
        idx = low.find(marker)
        if idx >= 0:
            q = text[idx + len(marker):].strip(" '\".,!?")
            if q:
                return _trim_trailing_clauses(q)
    return text.strip(" '\".,!?")


def classify_intent(raw_text: str) -> Intent:
    """Classify a user request into an Intent (offline, deterministic)."""
    text = (raw_text or "").strip()
    if not text:
        return Intent(text="", kind=IntentKind.UNKNOWN, confidence=1.0,
                      notes=["empty request"])

    low = text.lower()
    notes: list = []
    browser = _find_browser(low)

    # 1. Compound / explicit browser search ("open Brave and search X")
    if _looks_browser_search(text):
        query = extract_query_from_browser_search(text)
        if not query or query.lower() in (browser or ""):
            notes.append("browser search phrase present but no clear query")
            query = text
        return Intent(
            text=text, kind=IntentKind.BROWSER_SEARCH,
            query=query, browser=browser or "brave",
            confidence=0.92, notes=notes,
        )

    # 2. Explicit web research (no browser mentioned)
    if any(tok in low for tok in _WEB_RESEARCH_TRIGGERS):
        query = _trim_trailing_clauses(_trim_web_prefix(_strip_question_prefix(text))) or text
        return Intent(
            text=text, kind=IntentKind.WEB_RESEARCH,
            query=query, confidence=0.88, notes=["web trigger words"],
        )

    # 3. 'open <app>' style request (not a question, not a web/browser phrase)
    if not _looks_question(text):
        m = re.match(r"^(?:please\s+)?(?:open up|start up|open|launch|start|run)\s+(.+)$", low)
        if m:
            rest = m.group(1).strip()
            if rest.startswith(("http://", "https://", "www.")):
                return Intent(
                    text=text, kind=IntentKind.ACTION_COMMAND,
                    confidence=0.8, notes=["open url -> action routing"],
                )
            app = text.strip()
            for verb in ("open up", "start up", "launch", "open", "start", "run"):
                if app.lower().startswith(verb):
                    app = app[len(verb):].strip().lstrip(",").strip()
                    break
            return Intent(
                text=text, kind=IntentKind.OPEN_APP,
                app_name=app or rest, confidence=0.9, notes=["explicit open verb"],
            )

    # 4. Questions
    if _looks_question(text):
        lowered = " ".join(low.split())
        if any(w in lowered for w in _KNOWLEDGE_WORDS):
            query = _strip_question_prefix(text)
            return Intent(
                text=text, kind=IntentKind.ANSWER_KNOWLEDGE,
                query=query, confidence=0.85,
                notes=["knowledge question -> direct answer, no tools"],
            )
        if any(tok in lowered for tok in _REASONING_TRIGGERS):
            query = _strip_question_prefix(text)
            return Intent(
                text=text, kind=IntentKind.REASONING,
                query=query, confidence=0.8,
                notes=["reasoning question -> reasoned answer, no tools"],
            )
        return Intent(
            text=text, kind=IntentKind.CHITCHAT,
            query=text, confidence=0.6,
            notes=["generic question"],
        )

    # 5. Action commands (only non-questions)
    for verb in _ACTION_VERBS:
        if low.startswith(verb) or (" " + verb) in low:
            return Intent(
                text=text, kind=IntentKind.ACTION_COMMAND,
                confidence=0.7, notes=[f"action verb '{verb.strip()}'"],
            )

    return Intent(
        text=text, kind=IntentKind.UNKNOWN,
        confidence=0.4, notes=["no confident classification"],
    )


def plan_for(intent: Intent) -> list:
    """Decompose an Intent into ordered PlanSteps."""
    kind = intent.kind
    if kind == IntentKind.BROWSER_SEARCH:
        browser = intent.browser or "brave"
        return [
            PlanStep("open_browser", f"Launch {browser}", {"browser": browser}),
            PlanStep("browser_search", f"Search for '{intent.query}' in {browser}",
                     {"query": intent.query, "browser": browser}),
            PlanStep("extract_results", "Extract search result information",
                     {"query": intent.query}),
            PlanStep("synthesize", "Synthesize retrieved facts into an answer",
                     {"query": intent.query}),
        ]
    if kind == IntentKind.WEB_RESEARCH:
        return [
            PlanStep("web_research", f"Search the web for '{intent.query}'",
                     {"query": intent.query}),
            PlanStep("synthesize", "Synthesize retrieved facts into an answer",
                     {"query": intent.query}),
        ]
    if kind == IntentKind.OPEN_APP:
        return [
            PlanStep("open_app", f"Open {intent.app_name}", {"app_name": intent.app_name}),
        ]
    return [
        PlanStep("direct_answer", f"Answer directly: {intent.query or intent.text}",
                 {"question": intent.query or intent.text}),
    ]
