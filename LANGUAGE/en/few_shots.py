# langchain_service/prompt/few_shots.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
FEW_SHOT_DIR = BASE_DIR / "few_shots"

def load_few_shot_profile(name: str) -> Dict[str, Any]:
    path = FEW_SHOT_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))

def _dict_to_md(obj: Dict[str, Any]) -> str:
    t = str(obj.get("type") or "").lower().strip()

    if t == "clarify":
        clarify = obj.get("clarify") or {}
        q = str(clarify.get("question") or "")
        options = clarify.get("options") or []
        req = clarify.get("required_fields") or []

        lines = []
        if q:
            lines.append(f"**Clarifying question**\n- {q}")
        if options:
            lines.append("\n**Options**")
            for it in options[:4]:
                label = str(it.get("label") or "")
                lines.append(f"- {label}")
        if req:
            lines.append("\n**Additional details needed**")
            for r in req:
                lines.append(f"- {r}")
        return "\n".join(lines).strip()

    # answer
    ans = obj.get("answer") or {}
    summary = str(ans.get("summary") or "").strip()
    checks = ans.get("checks") or []
    steps = ans.get("steps") or []
    fallback = str(ans.get("fallback") or "").strip()

    lines = []
    if summary:
        lines.append("**Summary**\n- " + summary)
    if checks:
        lines.append("\n**Checks**")
        for c in checks[:6]:
            lines.append(f"- {c}")
    if steps:
        lines.append("\n**Steps**")
        for i, s in enumerate(steps[:10], 1):
            lines.append(f"{i}. {s}")
    if fallback:
        lines.append("\n**Additional info**\n- " + fallback)
    return "\n".join(lines).strip()

def few_shot_messages(profile: Dict[str, Any]) -> List[tuple[str, str]]:
    msgs: List[tuple[str, str]] = []
    for ex in profile.get("examples", []) or []:
        user = str(ex.get("user") or "")
        assistant = ex.get("assistant")

        msgs.append(("human", user))

        if isinstance(assistant, str):
            msgs.append(("ai", assistant))
        elif isinstance(assistant, dict):
            msgs.append(("ai", _dict_to_md(assistant)))
        else:
            msgs.append(("ai", str(assistant or "")))

    return msgs
