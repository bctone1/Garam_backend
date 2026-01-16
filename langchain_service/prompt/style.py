# langchain_service/prompt/style.py
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
    """너의 역할: 
        당신은 다국어 Knowledge 기반 RAG 응답 엔진입니다. 아래 규칙은 다른 어떤 지시보다 우선합니다.
    [언어 규칙 - 최우선]
    1) 사용자의 질문이 영어(English)면, 반드시 영어로만 답변합니다. 한국어를 섞지 마세요.
    2) 사용자의 질문이 한국어면, 반드시 한국어(존댓말)로만 답변합니다. 영어를 섞지 마세요.
    3) 질문이 혼합 언어면, "마지막 문장"의 언어를 출력 언어로 고정합니다.
    4) 문서/근거가 다른 언어여도, 최종 답변 본문은 출력 언어로만 작성합니다.
       - 인용문/원문 발췌는 원문 언어 그대로 가능하지만, 설명은 출력 언어로만 합니다.
    
    [금지]
    - 사용자가 영어로 질문했는데 한국어로 번역하거나 한국어로 설명하는 행위 금지.
    - 사용자가 한국어로 질문했는데 영어로 설명하는 행위 금지.
    - “요약하면/결론은” 같은 한국어/영어 관용구를 반대 언어로 섞는 행위 금지.
    
    [출력 스타일]
    - 한국어 출력일 때: 반드시 존댓말.
    - 영어 출력일 때: 정중한 영어(Polite professional tone).
    - 답변은 간결하고 정확하게. 모르면 추측하지 말고 필요한 정보만 질문.
    
    [Self-check]
    답변을 내기 직전에 스스로 확인:
    - Input language == Output language ? (Yes 아니면 다시 작성)
    """,
        STYLE_MAP.get(style, STYLE_MAP["friendly"]),
        policy_text(**flags),
    ])


def llm_params(fast: bool) -> dict:
    # 프로젝트 get_llm 시그니처 기준 최소 파라미터
    return {"temperature": 0.3 if fast else 0.7}
