from __future__ import annotations

import re

LANGUAGE_LABELS: dict[str, str] = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
}

_KOREAN_RE = re.compile(r"[가-힣]")
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff]")
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def _last_sentence(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    parts = re.split(r"[.!?\n。！？]", raw)
    for part in reversed(parts):
        p = part.strip()
        if p:
            return p
    return raw


def detect_language(text: str) -> str:
    segment = _last_sentence(text)
    if _KOREAN_RE.search(segment):
        return "ko"
    if _JAPANESE_RE.search(segment):
        return "ja"
    if _CHINESE_RE.search(segment):
        return "zh"
    return "en"


def needs_translation(text: str, target_lang: str) -> bool:
    return detect_language(text) != target_lang


def language_label(lang: str) -> str:
    return LANGUAGE_LABELS.get(lang, "English")
