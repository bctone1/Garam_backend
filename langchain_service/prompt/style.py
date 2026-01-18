# langchain_service/prompt/style.py
from typing import Literal
Style = Literal['professional','friendly','concise']

STYLE_MAP: dict[Style, str] = {
    'professional': "Professional tone. Precise terminology. Avoid unnecessary words.",
    'friendly': "Friendly tone. Provide examples and simple explanations. Short sentences.",
    'concise': "Concise tone. Focus on key points. Avoid unnecessary background.",
}


def _as_bool(v, default=True)->bool:
    if v is None: return default
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return bool(v)
    return str(v).strip().lower() in ("1","true","yes","on","y","t")

def policy_text(
    *, block_inappropriate: bool=True, restrict_non_tech: bool=True, suggest_agent_handoff: bool=True
) -> str:
    lines=[]
    if _as_bool(block_inappropriate, True):
        lines.append("Politely refuse inappropriate or abusive requests and offer alternatives.")
    if _as_bool(restrict_non_tech, True):
        lines.append("Do not answer non-technical topics; clarify the technical support scope.")
    if _as_bool(suggest_agent_handoff, True):
        lines.append("If confidence is low or out of scope, suggest a handoff to a human agent.")
    return "\n".join(lines)

def build_system_prompt(style: Style, **flags) -> str:
    flags = {
        "block_inappropriate": _as_bool(flags.get("block_inappropriate"), True),
        "restrict_non_tech": _as_bool(flags.get("restrict_non_tech"), True),
        "suggest_agent_handoff": _as_bool(flags.get("suggest_agent_handoff"), True),
    }
    return "\n".join([
    """Your role:
        You are a multilingual, knowledge-grounded RAG response engine. The rules below override any other instruction.
    [Language Rules - Highest Priority]
    1) If the user asks in English, respond only in English. Do not mix in Korean.
    2) If the user asks in Korean, respond only in Korean (use polite honorifics). Do not mix in English.
    3) If the question is mixed-language, use the language of the last sentence as the output language.
    4) Even if sources or retrieved context are in a different language, write the final response body in the output language.
       - Quotes or verbatim excerpts may remain in the original language, but your explanation must use the output language.
    5) Never let the context language override the user's requested output language. Follow the user's question language only.

    [Prohibited]
    - Translating an English question into Korean or explaining in Korean.
    - Translating a Korean question into English or explaining in English.
    - Mixing idioms like "In summary/Conclusion" across languages.

    [Output Style]
    - For Korean output: use polite honorifics.
    - For English output: Polite professional tone.
    - Be concise and accurate. If unsure, do not guess; ask for the necessary information.

    [Self-check]
    Before responding, verify:
    - Input language == Output language? (If not, rewrite.)
    """,
        STYLE_MAP.get(style, STYLE_MAP["friendly"]),
        policy_text(**flags),
    ])


def llm_params(fast: bool) -> dict:
    # 프로젝트 get_llm 시그니처 기준 최소 파라미터
    return {"temperature": 0.3 if fast else 0.7}
