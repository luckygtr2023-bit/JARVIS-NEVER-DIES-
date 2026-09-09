"""J.A.R.V.I.S. web-research execution.

Real, verifiable research helpers. Every function either returns genuine
retrieved content or an explicit, honest error — nothing is faked.

Two research methods exist and are reused from the existing architecture:
  1. ``web_search`` action helpers (DuckDuckGo, with a Gemini-grounded
     fallback) — used by SearchProviderChain here.
  2. Real-browser search via the existing ``open_app`` + ``browser_control``
     actions (Brave/Chrome/... are launched for real and the results page is
     extracted) — used by BrowserResearchSession here.

Browser execution requires a real desktop browser + Playwright at runtime.
That is why this module's browser path is driven through injectable adapter
functions: the exact same orchestration code runs in production and in
behavioural tests (which use a fake browser session).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── structured result types ─────────────────────────────────────────────────

@dataclass
class SourceResult:
    title: str
    snippet: str
    url: str
    rank: int = 0


@dataclass
class ResearchReport:
    ok: bool
    query: str
    method: str                       # duckduckgo | gemini | browser | none
    status: str = "ok"                # ok | empty | timeout | error
    results: list = field(default_factory=list)
    raw_text: str = ""
    error: Optional[str] = None
    warnings: list = field(default_factory=list)
    phases: list = field(default_factory=list)


class SearchUnavailable(RuntimeError):
    """All configured search providers failed."""


class SearchTimeout(RuntimeError):
    """A search provider timed out."""


# ── search providers (real) ─────────────────────────────────────────────────

def _ddg_provider(query: str, max_results: int = 6) -> list:
    """Reuse the app's DuckDuckGo search helper (actions/web_search.py)."""
    from actions.web_search import _ddg_search
    return _ddg_search(query, max_results=max_results)


def _gemini_provider(query: str) -> str:
    """Reuse the app's Gemini-grounded search helper (actions/web_search.py)."""
    from actions.web_search import _gemini_search
    return _gemini_search(query)


def _as_results(rows: list) -> list:
    out = []
    for i, r in enumerate(rows, 1):
        out.append(SourceResult(
            title=str(r.get("title", "") or ""),
            snippet=str(r.get("snippet", "") or ""),
            url=str(r.get("url", "") or ""),
            rank=i,
        ))
    return out


def search_web(query: str, max_results: int = 6,
               timeout_seconds: float = 25.0) -> ResearchReport:
    """Run a real web search (DuckDuckGo first, Gemini-grounded fallback).

    Never returns fabricated content. Empty or failed providers are reported
    explicitly through ``ResearchReport.status``.
    """
    query = (query or "").strip()
    report = ResearchReport(ok=False, query=query, method="none",
                            phases=["intent detected", "web search requested"])
    if not query:
        report.status = "error"
        report.error = "No search query supplied."
        return report

    errors: list[str] = []
    deadline = time.monotonic() + timeout_seconds

    # 1) DuckDuckGo (fast, no API key required)
    try:
        report.phases.append("searching duckduckgo")
        rows = _ddg_provider(query, max_results=max_results)
        if rows:
            report.ok = True
            report.method = "duckduckgo"
            report.results = _as_results(rows)
            report.status = "ok"
            report.phases.append(f"results loaded ({len(rows)} retrieved)")
            return report
        report.status = "empty"
        report.phases.append("duckduckgo returned no results")
    except Exception as exc:  # noqa: BLE001 - every provider error is surfaced
        if time.monotonic() > deadline:
            report.status = "timeout"
            report.error = f"SEARCH TIMEOUT - DuckDuckGo: {exc}"
            report.phases.append("search timed out")
            return report
        errors.append(f"DuckDuckGo: {exc}")
        report.phases.append(f"duckduckgo failed ({exc})")

    # 2) Gemini-grounded fallback (uses configured API key when present)
    try:
        if time.monotonic() > deadline:
            raise SearchTimeout("deadline exceeded")
        report.phases.append("falling back to gemini-grounded search")
        text = _gemini_provider(query)
        if text and text.strip():
            report.ok = True
            report.method = "gemini"
            report.raw_text = text.strip()
            report.status = "ok"
            report.warnings.append(
                "Gemini-grounded result used (no per-result URLs available)."
            )
            report.phases.append("results loaded (gemini grounding)")
            return report
        report.status = "empty"
        report.phases.append("gemini search returned no text")
    except Exception as exc:  # noqa: BLE001
        if "timeout" in str(exc).lower() or time.monotonic() > deadline:
            report.status = "timeout"
            report.error = f"SEARCH TIMEOUT - Gemini: {exc}"
            report.phases.append("search timed out")
            return report
        errors.append(f"Gemini: {exc}")
        report.phases.append(f"gemini search failed ({exc})")

    report.status = "error"
    report.error = "All search providers failed: " + "; ".join(errors)
    report.phases.append("all search providers failed")
    return report


# ── best-effort search-engine result parsing (pure, testable) ───────────────

def parse_search_results(raw_text: str, engine: str = "generic",
                         max_results: int = 8) -> list:
    """Best-effort extraction of (title, snippet, url) triples from a results
    page's visible text. Honest: returns whatever it can parse; callers treat
    an empty list as 'no parseable results' rather than inventing content."""
    if not raw_text or not raw_text.strip():
        return []
    text = raw_text.strip()
    results: list = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Pattern A — enumerated lines: "1. Title" then URL then snippet lines.
    current: Optional[dict] = None
    for line in lines:
        m = re.match(r"^(\d{1,2})[.)]\s+(.+)$", line)
        if m:
            if current and (current.get("title") or current.get("snippet")):
                results.append(current)
                if len(results) >= max_results:
                    break
            current = {"title": m.group(2), "snippet": "", "url": ""}
            continue
        if current is not None:
            if not current["url"] and re.match(r"^https?://\S+$", line):
                current["url"] = line
            elif line and len(line) > 20 and not current["snippet"]:
                current["snippet"] = line
    if current and (current.get("title") or current.get("snippet")):
        results.append(current)

    # Pattern B — URL-first blocks (snippet text above a bare URL line).
    if not results:
        current = None
        for line in lines:
            if re.match(r"^https?://\S+$", line) and current:
                current["url"] = line
                if current.get("title") or current.get("snippet"):
                    results.append(current)
                    current = None
                    if len(results) >= max_results:
                        break
                continue
            if current is not None and len(line) > 30 and not current["snippet"]:
                current["snippet"] = line
            else:
                current = {"title": line[:180], "snippet": "", "url": ""}

    out: list = []
    for i, r in enumerate(results[:max_results], 1):
        out.append(SourceResult(
            title=(r.get("title") or "").strip(),
            snippet=(r.get("snippet") or "").strip(),
            url=(r.get("url") or "").strip(),
            rank=i,
        ))
    return [r for r in out if (r.title or r.snippet)]


# ── real-browser search session ─────────────────────────────────────────────

class BrowserResearchSession:
    """Drives a real browser through the app's existing actions.

    Production adapters (default) call ``actions.open_app.open_app`` and
    ``actions.browser_control.browser_control``. Tests inject fakes.

    Phases are logged in order so failures are attributable:
    browser action requested -> browser launched -> query entered ->
    search submitted -> results loaded -> extraction succeeded/failed.
    """

    def __init__(
        self,
        open_app_fn: Optional[Callable[[dict], str]] = None,
        browser_control_fn: Optional[Callable[[dict], str]] = None,
        log: Optional[Callable[[str], None]] = None,
        search_engine: str = "duckduckgo",
    ):
        self._open_app = open_app_fn
        self._browser_control = browser_control_fn
        self._log = log or (lambda msg: print(f"[BrowserResearch] {msg}"))
        self._engine = search_engine

    # lazy production adapters
    def _open_app_fn(self) -> Callable[[dict], str]:
        if self._open_app is None:
            from actions.open_app import open_app as _oa
            return _oa
        return self._open_app

    def _browser_fn(self) -> Callable[[dict], str]:
        if self._browser_control is None:
            from actions.browser_control import browser_control as _bc
            return _bc
        return self._browser_control

    def search(self, query: str, browser: str = "brave",
               timeout_seconds: float = 45.0) -> ResearchReport:
        query = (query or "").strip()
        report = ResearchReport(
            ok=False, query=query, method="browser",
            phases=["intent detected", "browser action requested"],
        )
        if not query:
            report.status = "error"
            report.error = "No search query supplied."
            return report
        deadline = time.monotonic() + timeout_seconds
        try:
            self._log("browser action requested")
            self._open_app_fn()({"app_name": browser})
            report.phases.append("browser launched")

            self._log("query entered")
            search_result = self._browser_fn()({
                "action": "search",
                "query": query,
                "engine": self._engine,
                "browser": browser,
            })
            report.phases.append("search submitted")
            self._log("search submitted")

            if time.monotonic() > deadline:
                report.status = "timeout"
                report.error = "SEARCH TIMEOUT - browser session exceeded deadline."
                report.phases.append("browser search timed out")
                return report

            # Wait for results to settle, then extract visible page text.
            wait_result = self._browser_fn()({
                "action": "wait_for_results",
                "timeout_ms": 12000,
            })
            if "timed out" in wait_result.lower() or "error" in wait_result.lower():
                report.warnings.append(f"Results wait warning: {wait_result}")

            self._log("results loaded")
            report.phases.append("results loaded")

            self._log("extraction started")
            extracted = self._browser_fn()({
                "action": "extract_search_results",
                "engine": self._engine,
                "max_results": 8,
            })
            report.raw_text = extracted or ""
            parsed = parse_search_results(extracted, engine=self._engine)
            if parsed:
                report.results = parsed
                report.ok = True
                report.status = "ok"
                report.phases.append(f"extraction succeeded ({len(parsed)} results)")
                self._log("extraction succeeded")
            else:
                report.status = "empty"
                report.warnings.append(
                    "Browser results page opened but no parseable results were "
                    "extracted (page may require interaction or blocked content)."
                )
                report.phases.append("extraction failed - no parseable results")
                self._log("extraction failed - no parseable results")
            return report

        except Exception as exc:  # noqa: BLE001
            report.status = "error"
            report.error = f"Browser search failed: {exc}"
            report.phases.append(f"browser search failed ({exc})")
            self._log("browser search failed")
            return report


# ── evidence formatting for the reasoning layer ─────────────────────────────

def format_evidence(report: ResearchReport, top_n: int = 6) -> str:
    """Turn a ResearchReport into a labelled evidence block for the LLM.

    Retrieved facts are clearly separated from model reasoning: the prompt
    template instructs the model to answer ONLY from the RETRIEVED FACTS and
    to say so when the facts are insufficient.
    """
    lines = ["RETRIEVED FACTS (from a real search; do not invent additional facts):"]
    if report.results:
        for r in report.results[:top_n]:
            url = f" ({r.url})" if r.url else ""
            lines.append(f"- {r.title}{url}: {r.snippet}")
    elif report.raw_text:
        lines.append(report.raw_text[:1200])
    else:
        lines.append("(no facts were retrieved)")
    lines.append("")
    lines.append("RULES:")
    lines.append("- Use ONLY the retrieved facts above to answer the user.")
    lines.append("- If the facts are insufficient, say so explicitly and state what is unknown.")
    lines.append("- Clearly separate what is retrieved versus what is your inference.")
    if report.warnings:
        lines.append("")
        lines.append("WARNINGS:")
        lines.extend(f"- {w}" for w in report.warnings)
    return "\n".join(lines)
