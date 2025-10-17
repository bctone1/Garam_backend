from typing import Literal
Style = Literal['professional','friendly','concise']

STYLE_MAP: dict[Style, str] = {
    'professional': "전문적 톤. 정확한 용어. 불필요한 말 금지.",
    'friendly': "친근한 톤. 예시와 쉬운 설명. 짧은 문장.",
    'concise': "간결한 톤. 핵심만. 불필요한 배경 설명 금지.",
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
        lines.append("부적절하거나 욕설 포함 질문은 정중히 거절하고 대안을 제시.")
    if _as_bool(restrict_non_tech, True):
        lines.append("기술지원 외 주제는 답변하지 말고 기술 범위를 안내 해 준다.")
    if _as_bool(suggest_agent_handoff, True):
        lines.append("확신 낮음 또는 범위 밖이면 상담원 연결을 제안.")
    return "\n".join(lines)

def build_system_prompt(style: Style, **flags) -> str:
    flags = {
        "block_inappropriate": _as_bool(flags.get("block_inappropriate"), True),
        "restrict_non_tech": _as_bool(flags.get("restrict_non_tech"), True),
        "suggest_agent_handoff": _as_bool(flags.get("suggest_agent_handoff"), True),
    }
    return "\n".join([
        "너의 역할: knowledge 기반 RAG 응답 엔진.",
        STYLE_MAP.get(style, STYLE_MAP["friendly"]),
        policy_text(**flags),
    ])


def llm_params(fast: bool) -> dict:
    # 프로젝트 get_llm 시그니처 기준 최소 파라미터
    return {"temperature": 0.3 if fast else 0.7}
