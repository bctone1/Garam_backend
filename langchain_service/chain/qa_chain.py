# langchain_service/chain/qa_chain.py
from __future__ import annotations

import os
import re
import logging
from operator import itemgetter
from typing import Optional, Callable, List, Any

from sqlalchemy.orm import Session

from langchain_core.runnables import RunnableLambda, RunnableMap
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from crud import model as crud_model
from service.knowledge_retrieval import retrieve_topk_hybrid
from langchain_service.prompt.style import build_system_prompt, llm_params, STYLE_MAP
from langchain_service.llm.translator import detect_language, needs_translation, language_label
from langchain_service.prompt.few_shots import load_few_shot_profile, few_shot_messages
from core import config

log = logging.getLogger("api_cost")
DEBUG_RAG_URL = os.getenv("DEBUG_RAG_URL") == "1"

# garampos detail url 템플릿
_GARAMPOS_DETAIL_URL_TEMPLATE = (
    "http://m.garampos.co.kr/bbs_shop/read.htm"
    "?me_popup=&auto_frame=&cate_sub_idx=0&search_first_subject=&list_mode=board"
    "&board_code=rwdboard&search_key=&key=&page=1&idx={idx}"
)


def _dbg_snip(s: str, n: int = 420) -> str:
    return (s or "").replace("\n", "\\n")[:n]


def _dbg_has_broken_url(s: str) -> bool:
    t = s or ""
    if "read.htm?" in t and "idx=" not in t:
        return True
    if re.search(r'href="[^"]*\n[^"]*"', t, flags=re.IGNORECASE):
        return True
    if "search_first_subject=" in t and "idx=" not in t:
        return True
    return False


def _is_good_download_url(url: str) -> bool:
    """
    다운로드/상세 링크로 쓰기 적합한지 필터링
    - idx= 가 있어야 함
    - search_first_subject=만 있고 idx= 없으면 제외
    """
    u = (url or "").strip()
    if not u:
        return False
    if "read.htm?" in u and "idx=" in u:
        return True
    return False


def _collect_source_urls_from_text(text: str) -> List[str]:
    """
    chunk_text 안에서 정상 URL만 최대한 뽑아내기.
    - detail_url 필드(JSON)
    - 일반 URL 토큰
    - page_id 로 idx 재구성(가능할 때)
    """
    t = text or ""
    out: List[str] = []

    # 1) JSON detail_url 우선
    for m in re.finditer(r'"detail_url"\s*:\s*"([^"]+)"', t, flags=re.IGNORECASE):
        url = m.group(1).strip()
        if _is_good_download_url(url):
            out.append(url)

    # 2) 텍스트 내 URL 토큰
    #    괄호/따옴표/공백 전까지 잘라서 URL만 잡음
    for m in re.finditer(r'(https?://[^\s<>"\)\]]+)', t, flags=re.IGNORECASE):
        url = m.group(1).strip()
        if _is_good_download_url(url):
            out.append(url)

    # 3) page_id 있으면 idx로 복원
    #    (네 데이터 구조에 page_id=idx 인 케이스가 많아서 응급처치로 매우 잘 먹힘)
    for m in re.finditer(r'"page_id"\s*:\s*(\d+)', t, flags=re.IGNORECASE):
        idx = m.group(1)
        url = _GARAMPOS_DETAIL_URL_TEMPLATE.format(idx=idx)
        if _is_good_download_url(url):
            out.append(url)

    # 중복 제거(순서 유지)
    seen = set()
    uniq: List[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _append_sources_section(context: str, chunks: list[Any]) -> str:
    """
    context 마지막에 [SOURCES] 섹션을 붙여서
    LLM이 깨진 링크 대신 여기의 URL을 그대로 쓰도록 강제한다.
    """
    urls: List[str] = []
    for c in chunks or []:
        ct = getattr(c, "chunk_text", "") or ""
        urls.extend(_collect_source_urls_from_text(ct))

    # 중복 제거(순서 유지)
    seen = set()
    uniq: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)

    if not uniq:
        return context

    # 마크다운 자동 링크(<...>)로 제공 (쿼리스트링 안 잘리게)
    lines = ["", "[SOURCES]"]
    for u in uniq[:10]:
        lines.append(f"- <{u}>")

    return (context or "") + "\n" + "\n".join(lines) + "\n"


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

    # Output format guidance + link enforcement rules
    system_txt = (
        system_txt
        + "\n\nAdditional instructions:\n"
        + "- Always respond in Markdown (no code fences).\n"
        + "- Append a final HTML comment block with metadata in this format:\n"
        + "  <!--\n"
        + "  STATUS: ok|no_knowledge|need_clarification\n"
        + "  REASON_CODE: <optional>\n"
        + "  CITATIONS: chunk_id=1,knowledge_id=2,page_id=3,score=0.42 | chunk_id=...\n"
        + "  -->\n"
        + "- When status=ok, the answer must be present and CITATIONS must include at least 1 item.\n"
        + "- When status=no_knowledge or need_clarification, keep the answer concise and set CITATIONS to empty.\n"
        + "- Ground your answer strictly in the provided context.\n"
        + "- Respond in the same language as the question (Korean/English/Chinese/Japanese).\n"
        + "- Do not switch output language based on the context language; follow the user's question language only.\n"
        + "- If force_clarify is True, set status=need_clarification and answer with a clarifying question.\n"
        + "- Use only the URLs in the [SOURCES] section for download/external links.\n"
    )

    #  few-shot 로드(없으면 조용히 스킵)
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
        fs_msgs = few_shot_messages(profile) or []

    def _clip_context(ctx: Any) -> str:
        if ctx is None:
            return ""
        return str(ctx)[:max_ctx_chars]

    def _retrieve(question: str) -> str:
        vec = text_to_vector(question)
        chunks = retrieve_topk_hybrid(
            db,
            query_vector=vec,
            knowledge_id=knowledge_id,
            top_k=top_k,
            query_text=question,
        )

        # 기본 context
        context = "\n\n".join((getattr(c, "chunk_text", "") or "") for c in chunks)[:max_ctx_chars]
        # URL 깨짐 방지: SOURCES 섹션을 서버가 붙여준다
        context = _append_sources_section(context, chunks)

        # ===== [DEBUG] URL 깨짐 진단: retrieval 직후 =====
        if DEBUG_RAG_URL:
            try:
                log.info(
                    "[URL-RETR] q=%s knowledge_id=%s top_k=%d got=%d",
                    (question or "")[:120],
                    knowledge_id,
                    top_k,
                    len(chunks) if chunks else 0,
                )
                for i, c in enumerate((chunks or [])[:8]):
                    t = (getattr(c, "chunk_text", "") or "")
                    cid = getattr(c, "id", None)
                    log.info(
                        "[URL-RETR] #%d chunk_id=%s has_read=%s has_idx=%s has_href=%s",
                        i,
                        cid,
                        ("read.htm?" in t),
                        ("idx=" in t),
                        ("href=" in t),
                    )
                    if _dbg_has_broken_url(t):
                        log.info("[URL-RETR] #%d text=%s", i, _dbg_snip(t, 520))

                # SOURCES 결과도 같이 확인
                srcs = _collect_source_urls_from_text(context)
                log.info("[URL-RETR] sources_found=%d", len(srcs))
                for i, u in enumerate(srcs[:10]):
                    log.info("[URL-RETR] source[%d]=%s", i, u)
            except Exception as e:
                log.exception("[URL-RETR] debug failed: %s", e)

        return context[:max_ctx_chars]

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
            "Refer to the following context.\n"
            "[Context Start]\n{context}\n[Context End]\n\n"
            "Question: {question}\n"
            "force_clarify: {force_clarify}\n\n"
            "Output rules: Markdown only / no code blocks / answer in the question language (Korean/English/Chinese/Japanese)\n",
        )
    )

    prompt = ChatPromptTemplate.from_messages(messages)

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

    answer_chain = (
        base
        | enrich
        | prompt
        | llm
        | StrOutputParser()
    )

    translator_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a translation engine. Translate the text to {target_language}.\n"
                "Preserve URLs, product names, and technical terms.\n"
                "Keep Markdown formatting and list structure.\n"
                "Do not add new information or omit content.\n"
                "Never use code blocks.",
            ),
            ("human", "{text}"),
        ]
    )

    translator_llm = get_llm(
        provider=provider,
        model=model,
        temperature=0.0,
        streaming=False,
    )

    if callbacks:
        try:
            translator_llm = translator_llm.with_config(callbacks=callbacks, run_name="translate_llm")
        except Exception:
            pass

    translate_chain = translator_prompt | translator_llm | StrOutputParser()

    def _translate_if_needed(payload: dict) -> str:
        question = payload.get("question", "") or ""
        answer = payload.get("answer", "") or ""
        target_lang = detect_language(question)
        if not answer:
            return answer
        if not needs_translation(answer, target_lang):
            return answer
        return translate_chain.invoke(
            {"text": answer, "target_language": language_label(target_lang)}
        )

    return (
        RunnableMap({"answer": answer_chain, "question": itemgetter("question")})
        | RunnableLambda(_translate_if_needed)
    )
