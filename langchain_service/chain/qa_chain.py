# langchain_service/chain/qa_chain.py
from __future__ import annotations

from operator import itemgetter
from typing import Optional, Callable, List, Any

from sqlalchemy.orm import Session

from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from crud import model as crud_model
from service.knowledge_retrieval import retrieve_topk_hybrid
from langchain_service.prompt.style import build_system_prompt, llm_params, STYLE_MAP
from langchain_service.prompt.few_shots import load_few_shot_profile, few_shot_messages
from core import config


def make_qa_chain(
    db: Session,
    get_llm: Callable[..., object],
    text_to_vector: Callable[[str], list[float]],
    *,
    knowledge_id: Optional[int] = None,
    top_k: int = 8,
    policy_flags: dict | None = None,
    style: Optional[str] = None,
    max_ctx_chars: int = 12000,
    restrict_to_kb: bool = True,
    streaming: bool = False,
    callbacks: Optional[List[Any]] = None,
    use_input_context: bool = False,
    few_shot_profile: str = "support_md",
):
    m = crud_model.get_single(db)
    if not m:
        raise RuntimeError("model not initialized")

    # 1) 스타일 소스 결정: 인자 > DB > 기본값
    style_key = style or getattr(m, "response_style", None) or "friendly"
    if style_key not in STYLE_MAP:
        style_key = "friendly"

    system_txt = build_system_prompt(style=style_key, **(policy_flags or {}))

    # 출력 형식 지침
    system_txt = (
        system_txt
        + "\n\n추가 지침:\n"
        + "- 답변은 마크다운으로 작성해. (굵게(**), 목록(-), 번호(1.) 사용 가능)\n"
        + "- 코드블록은 절대 사용하지 마. (``` 또는 ```json 포함 전부 금지)\n"
        + "- JSON만 출력하는 형식은 금지야. 일반 문장 + 목록 형태로 답해.\n"
        + "- 제공된 컨텍스트에 근거해서만 답해.\n"
        + "- 컨텍스트 근거가 부족하면 '없음'으로 끝내지 말고, 필요한 정보를 물어보는 확인 질문(clarify)으로 전환해.\n"
        + "- force_clarify가 True면 답변 대신 확인 질문만 해.\n"
    )

    # ✅ few-shot 로드(없으면 조용히 스킵)
    profile = None
    for cand in [few_shot_profile, "support_v1"]:
        try:
            profile = load_few_shot_profile(cand)
            break
        except FileNotFoundError:
            continue
        except Exception:
            continue

    fs_msgs: list[tuple[str, str]] = []
    if profile:
        # rules는 JSON 전용일 수 있어서 여기서는 강제 적용하지 않고 examples만 사용
        fs_msgs = few_shot_messages(profile) or []

    def _clip_context(ctx: Any) -> str:
        if ctx is None:
            return ""
        return str(ctx)[:max_ctx_chars]

    def _retrieve(question: str) -> str:
        # use_input_context=True면 이 함수는 호출되지 않음(=임베딩/검색 0회)
        vec = text_to_vector(question)
        chunks = retrieve_topk_hybrid(
            db,
            query_vector=vec,
            knowledge_id=knowledge_id,
            top_k=top_k,
            query_text=question,
        )
        return "\n\n".join((getattr(c, "chunk_text", "") or "") for c in chunks)[:max_ctx_chars]

    def _has_specific_markers(q: str) -> bool:
        ql = q.lower()
        if any(ch.isdigit() for ch in q):
            return True
        specific = [
            "mm", "57", "80", "감열", "영수증", "모델", "기종",
            "어디", "어디서", "어떻게", "방법",
            "교체", "장착", "설치", "연결", "브라우저",
            "에러", "오류", "오류코드", "코드",
        ]
        return any(s in ql for s in specific)

    def _should_clarify(question: str, context: str) -> bool:
        q = (question or "").strip()
        ctx = (context or "").strip()

        if len(ctx) < 40:
            return True
        if not q:
            return True

        wc = len(q.split())
        if not _has_specific_markers(q):
            if len(q) <= 6:
                return True
            if wc <= 2 and len(q) <= 12:
                return True

            ambiguous = ["주문", "접수", "설정", "문의", "문제", "안됨", "안돼", "안되", "오류", "에러"]
            if any(a in q for a in ambiguous) and wc <= 3:
                return True

        return False

    retriever = RunnableLambda(_retrieve)

    # context 소스 선택: runner 주입(context) vs 내부 검색(retriever)
    if use_input_context:
        context_runnable = itemgetter("context") | RunnableLambda(_clip_context)
    else:
        context_runnable = itemgetter("question") | retriever

    base = RunnableMap(
        {
            "question": itemgetter("question"),
            "context": context_runnable,
        }
    )

    enrich = RunnableLambda(
        lambda d: {
            **d,
            "force_clarify": _should_clarify(d.get("question", ""), d.get("context", "")),
        }
    )

    messages: list[tuple[str, str]] = [("system", system_txt)]
    if fs_msgs:
        messages.extend(fs_msgs)

    messages.append(
        (
            "human",
            "다음 컨텍스트를 참고해.\n"
            "[컨텍스트 시작]\n{context}\n[컨텍스트 끝]\n\n"
            "질문: {question}\n"
            "force_clarify: {force_clarify}\n\n"
            "출력 규칙: 마크다운 OK / 코드블록( ``` ) 금지 / JSON-only 금지\n",
        )
    )

    prompt = ChatPromptTemplate.from_messages(messages)

    # === LLM init ===
    params = llm_params(m.fast_response_mode)
    provider = getattr(config, "LLM_PROVIDER", "openai")
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))
    temperature = params.get("temperature", 0.7)

    llm = get_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        streaming=streaming,
    )

    if callbacks:
        try:
            llm = llm.with_config(callbacks=callbacks, run_name="qa_llm")
        except Exception:
            pass

    return (
        base
        | enrich
        | prompt
        | llm
        | StrOutputParser()
    )
