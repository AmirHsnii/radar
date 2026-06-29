"""
RouterAgent — language detection for incoming news articles.

Three-step strategy (AGENTS.md spec):
  1. Rule-based   — count Arabic/Persian codepoints (U+0600–U+06FF)
                    > 30% → fa, confidence 0.99   (fast, free, reliable)
  2. langdetect   — statistical ML library
                    prob > 0.90 → use result      (fast, free)
  3. LLM fallback — ai.fast_model via OpenRouter   (slow, costs $)
                    Only reached for genuinely ambiguous text.

Backward-compat surface:
  detect_language(text) → str      — sync, rule + langdetect only (no LLM)
  needs_translation(lang) → bool   — used by orchestrator
  router_agent                      — async singleton for new code
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

import structlog
from langdetect import LangDetectException, detect_langs

from app.config import settings

log = structlog.get_logger(__name__)

_FA_RANGE_RE = re.compile(r"[؀-ۿ]")   # U+0600–U+06FF Arabic/Persian block
_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class LanguageResult:
    language: str      # "fa" | "en"
    method: str        # "rule" | "langdetect" | "llm"
    confidence: float  # 0.0 – 1.0


# ---------------------------------------------------------------------------
# Text normalisation (for detection, not for dedup)
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """
    Light cleaning before language detection:
      1. Unicode NFKC — collapses Arabic presentation forms to base letters
      2. Remove URLs  — would confuse langdetect
      3. Collapse whitespace

    Does NOT strip punctuation — langdetect needs sentence structure to work.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _URL_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# RouterAgent
# ---------------------------------------------------------------------------

class RouterAgent:
    """
    Detects whether a news article is Farsi ("fa") or English ("en").

    Call the async detect() for full three-step detection.
    The sync helpers _rule_based() and _langdetect() are public so the
    synchronous backward-compat wrapper can call them without async.
    """

    # ------------------------------------------------------------------
    # Public async entry point
    # ------------------------------------------------------------------

    async def detect(self, title: str, content_preview: str = "") -> LanguageResult:
        """
        Full three-step detection with logging of which method was used.
        content_preview should be the first ≤300 characters of the article.
        """
        combined = normalize_text(f"{title} {content_preview[:300]}")

        # Step 1 — rule-based (free, instant)
        result = self._rule_based(combined)
        if result is not None:
            log.debug(
                "router.rule_based",
                language=result.language, confidence=result.confidence,
            )
            return result

        # Step 2 — langdetect (free, ~1 ms)
        result = self._langdetect(combined)
        if result is not None:
            log.debug(
                "router.langdetect",
                language=result.language, confidence=result.confidence,
            )
            return result

        # Step 3 — LLM (costs money; only for genuinely ambiguous text)
        log.info("router.llm_fallback_triggered", title_preview=title[:80])
        result = await self._llm_detect(title, content_preview)
        log.debug(
            "router.llm_result",
            language=result.language, confidence=result.confidence,
        )
        return result

    # ------------------------------------------------------------------
    # Step 1 — rule-based
    # ------------------------------------------------------------------

    def _rule_based(self, text: str) -> LanguageResult | None:
        """
        Count Arabic/Persian characters (U+0600–U+06FF).

        > 30% → clearly Farsi (confidence 0.99)
        < 5%  → clearly English (confidence 0.95)  — skip langdetect
        else  → ambiguous, return None
        """
        if not text:
            return None
        chars = text.replace(" ", "")
        if not chars:
            return None

        fa_count = len(_FA_RANGE_RE.findall(chars))
        ratio = fa_count / len(chars)

        if ratio > 0.30:
            return LanguageResult(language="fa", method="rule", confidence=0.99)
        if ratio < 0.05 and len(chars) >= 20:
            # Almost no Arabic chars and enough text → safe to call it English
            return LanguageResult(language="en", method="rule", confidence=0.95)
        return None

    # ------------------------------------------------------------------
    # Step 2 — langdetect
    # ------------------------------------------------------------------

    def _langdetect(self, text: str) -> LanguageResult | None:
        """
        Run langdetect.detect_langs() and return a result if the top
        prediction is confident (prob > 0.90), else None.
        """
        if not text or len(text.strip()) < 10:
            return None

        try:
            results = detect_langs(text[:500])
        except LangDetectException:
            return None

        if not results:
            return None

        best = results[0]
        lang = best.lang
        prob = float(best.prob)

        if prob <= 0.90:
            return None

        # "ar" (Arabic) and "fa" (Farsi) share the same script; treat both
        # as "fa" because our sources are either EN or FA/AR.
        if lang in ("fa", "ar"):
            return LanguageResult(language="fa", method="langdetect", confidence=prob)
        if lang == "en":
            return LanguageResult(language="en", method="langdetect", confidence=prob)

        return None   # unexpected language → let LLM decide

    # ------------------------------------------------------------------
    # Step 3 — LLM fallback
    # ------------------------------------------------------------------

    async def _llm_detect(self, title: str, content_preview: str) -> LanguageResult:
        """
        Ask the cheap fast model to classify the language.
        Returns "en" with confidence 0.50 if the call fails, so the
        pipeline can continue rather than crashing on ambiguous input.
        """
        try:
            from app.core.openrouter import get_client
            from app.modules.pipeline.prompts import get_agent_prompt
            model = str(await settings.get("ai.fast_model", "google/gemini-flash-1.5"))
            client = get_client()
            system_prompt = await get_agent_prompt("router")

            llm_result = await client.chat(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": f"Title: {title}\nContent: {content_preview[:300]}",
                    },
                ],
                max_tokens=20,
                temperature=0.0,
                task_name="language_detection",
                response_format={"type": "json_object"},
            )

            data = json.loads(llm_result.content)
            lang = data.get("language", "en")
            if lang not in ("fa", "en"):
                lang = "en"
            return LanguageResult(language=lang, method="llm", confidence=0.85)

        except Exception as exc:
            log.warning("router.llm_detect_failed", error=str(exc))
            return LanguageResult(language="en", method="llm", confidence=0.50)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

router_agent = RouterAgent()


# ---------------------------------------------------------------------------
# Backward-compatible synchronous helpers (used by orchestrator)
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Sync language detection using rule-based + langdetect only.
    No LLM call, no async — safe to call from both sync and async contexts.
    Defaults to "en" when both methods are uncertain.
    """
    normalized = normalize_text(text[:400])

    result = router_agent._rule_based(normalized)
    if result:
        return result.language

    result = router_agent._langdetect(normalized)
    if result:
        return result.language

    return "en"


def needs_translation(language: str) -> bool:
    """Return True for English articles that must be translated to Farsi."""
    return language == "en"
