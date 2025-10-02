from typing import Literal
Style = Literal['professional','friendly','concise']

STYLE_MAP: dict[Style, str] = {
    'professional': "전문적 톤. 정확한 용어. 불필요한 말 금지.",
    'friendly': "친근한 톤. 예시와 쉬운 설명. 짧은 문장.",
    'concise': "간결한 톤. 핵심만. 불필요한 배경 설명 금지.",
}

def policy_text(*, block_inappropriate: bool, restrict_non_tech: bool,
                suggest_agent_handoff: bool) -> str:
    lines = []
    if block_inappropriate:
        lines.append("부적절하거나 욕설 포함 질문은 정중히 거절하고 대안을 제시.")
    if restrict_non_tech:
        lines.append("기술지원 외 주제는  답변하지 말고 기술 범위를 안내 해 준다.")
    if suggest_agent_handoff:
        lines.append("확신 낮음 또는 범위 밖이면 상담원 연결을 제안.")
    return "\n".join(lines)


def build_system_prompt(style: Style, **flags) -> str:
    return "\n".join([
        "너의 역할: knowledge 기반 RAG 응답 엔진.",
        STYLE_MAP[style],
        policy_text(**flags)
    ])


def llm_params(fast: bool) -> dict:
    # 프로젝트 get_llm 시그니처 기준 최소 파라미터
    return {"temperature": 0.3 if fast else 0.7}
