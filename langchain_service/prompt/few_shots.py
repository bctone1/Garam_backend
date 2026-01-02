from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
FEW_SHOT_DIR = BASE_DIR / "few_shots"

def load_few_shot_profile(name: str) -> Dict[str, Any]:
    path = FEW_SHOT_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data

def few_shot_messages(profile: Dict[str, Any]) -> List[tuple[str, str]]:
    msgs: List[tuple[str, str]] = []
    for ex in profile.get("examples", []):
        msgs.append(("human", ex["user"]))
        msgs.append(("ai", json.dumps(ex["assistant"], ensure_ascii=False)))
    return msgs
