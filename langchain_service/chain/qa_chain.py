# langchain_service/chain/qa_chain.py
from __future__ import annotations

import json
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
    force_json_output: bool = True,
    few_shot_profile: str = "support_v1",  # 없으면 자동 fallback
):
    m = crud_model.get_single(db)
    if not m:
        raise RuntimeError("model not initialized")

    # 1) 스타일 소스 결정: 인자 > DB > 기본값
    style_key = style or getattr(m, "response_style", None) or "friendly"
    if style_key not in STYLE_MAP:
        style_key = "friendly"

    system_txt = build_system_prompt(style=style_key, **(policy_flags or {}))

    def _clip_context(ctx: Any) -> str:
        if ctx is None:
            return ""
        s = str(ctx)
        return s[:max_ctx_chars]

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
        return "\n\n".join(getattr(c, "chunk_text", "") for c in chunks)[:max_ctx_chars]

    def _has_specific_markers(q: str) -> bool:
        ql = q.lower()
        # 숫자/규격/모델/질문 의도(어디서/어떻게/방법 등) 들어가면 "구체적"으로 간주
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

        # 컨텍스트가 거의 없으면(검색 실패/저품질) -> clarify 우선
        if len(ctx) < 40:
            return True

        if not q:
            return True

        # 아주 짧고(또는 단어 수 적고) 구체 마커 없으면 -> clarify
        wc = len(q.split())
        if not _has_specific_markers(q):
            if len(q) <= 6:
                return True
            if wc <= 2 and len(q) <= 12:
                return True

            # 다의어/범용어 + 짧은 질의는 clarify
            ambiguous = ["주문", "접수", "설정", "문의", "문제", "안됨", "안돼", "안되", "오류", "에러"]
            if any(a in q for a in ambiguous) and wc <= 3:
                return True

        return False

    # === few-shot profile 로드 (파일명 오타/버전 대비 fallback) ===
    profile = None
    if force_json_output:
        for name in [few_shot_profile, "support_v1", "support_v1"]:
            try:
                profile = load_few_shot_profile(name)
                break
            except FileNotFoundError:
                continue

    json_contract_block = ""
    fs_msgs: list[tuple[str, str]] = []
    if force_json_output and profile:
        contract = profile.get("output_contract") or {}
        rules = profile.get("rules") or []

        json_contract_block = (
                "\n\n"
                "IMPORTANT: You must respond with a single valid json object only.\n"
                "반드시 **유효한 json 객체 하나만** 출력해. (코드블록/마크다운/설명 문장 금지)\n"
                "출력 계약(schema 비슷한 형태):\n"
                f"{json.dumps(contract, ensure_ascii=False, indent=2)}\n\n"
                "규칙:\n- " + "\n- ".join(rules) + "\n\n"
                 "추가 규칙:\n"
                 "- force_clarify=true이면 반드시 type=clarify로만 응답\n"
                 "- answer는 제공된 컨텍스트에 근거해서만 작성\n"
                 "- 컨텍스트 근거가 부족하면 '없음'이라고 끝내지 말고 clarify로 전환\n"
        )
        fs_msgs = few_shot_messages(profile)

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

    # === prompt: system + few-shot + human ===
    messages: list[tuple[str, str]] = [
        ("system", system_txt + json_contract_block),
    ]
    if fs_msgs:
        messages.extend(fs_msgs)

    messages.append(
        (
            "human",
            "Return only valid json.\n"
            "다음 컨텍스트를 참고해.\n"
            "[컨텍스트 시작]\n{context}\n[컨텍스트 끝]\n\n"
            "질문: {question}\n"
            "force_clarify: {force_clarify}\n",
        )
    )

    prompt = ChatPromptTemplate.from_messages(messages)

    # === LLM init ===
    params = llm_params(m.fast_response_mode)
    provider = getattr(config, "LLM_PROVIDER", "openai")
    model = getattr(config, "LLM_MODEL", getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini"))

    # JSON 출력 안정성 위해 temperature 낮추기
    temperature = 0.0 if force_json_output else params.get("temperature", 0.7)

    # OpenAI면 가능하면 JSON mode(지원 안 하면 무시)
    llm_kwargs = {}
    if force_json_output and str(provider).lower() == "openai":
        # ChatOpenAI는 보통 model_kwargs로 response_format 전달 가능
        llm_kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    try:
        llm = get_llm(
            provider=provider,
            model=model,
            temperature=temperature,
            streaming=streaming,
            **llm_kwargs,
        )
    except TypeError:
        # get_llm이 model_kwargs를 안 받는 경우 fallback
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
