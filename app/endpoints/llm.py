from __future__ import annotations
from typing import Iterable, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from crud import chat as crud_chat
from crud import knowledge as crud_knowledge
from database.session import get_db
from langchain_service.chain.qa_chain import make_qa_chain
from langchain_service.embedding.get_vector import text_to_vector
from langchain_service.llm.setup import get_llm
from schemas.llm import ChatQARequest, QARequest, QAResponse, QASource
from service.stt import transcribe_bytes
from schemas.llm import STTResponse, STTQAParams
import os, tempfile, subprocess, shutil, requests

router = APIRouter(tags=["LLM"])
CLOVA_STT_URL = os.getenv("CLOVA_STT_URL")

def _ensure_session(db: Session, session_id: int) -> None:
    if not crud_chat.get_session(db, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")


def _to_vector(question: str) -> list[float]:
    vector = text_to_vector(question)
    if vector is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="임베딩 생성에 실패했습니다.")
    if hasattr(vector, "tolist"):
        vector_list = vector.tolist()
    else:
        vector_list = list(vector)
    if not vector_list:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="임베딩 생성에 실패했습니다.")
    return [float(v) for v in vector_list]


def _update_last_user_vector(db: Session, session_id: int, vector: Iterable[float]) -> None:
    message = crud_chat.last_by_role(db, session_id, "user")
    if not message:
        return
    message.vector_memory = list(vector)
    db.add(message)
    db.commit()
    db.refresh(message)


def _build_sources(db: Session, vector: list[float], knowledge_id: Optional[int], top_k: int) -> list[QASource]:
    chunks = crud_knowledge.search_chunks_by_vector(
        db,
        query_vector=vector,
        knowledge_id=knowledge_id,
        top_k=top_k,
    )
    return [
        QASource(
            chunk_id=chunk.id,
            knowledge_id=chunk.knowledge_id,
            page_id=chunk.page_id,
            chunk_index=chunk.chunk_index,
            text=chunk.chunk_text,
        )
        for chunk in chunks
    ]


def _run_qa(
    db: Session,
    *,
    question: str,
    knowledge_id: Optional[int],
    top_k: int,
    session_id: Optional[int] = None,
    policy_flags: Optional[dict] = None,
    style: Optional[str] = None,
) -> QAResponse:
    vector = _to_vector(question)
    if session_id is not None:
        _update_last_user_vector(db, session_id, vector)

    try:
        chain = make_qa_chain(
            db,
            get_llm,
            text_to_vector,
            knowledge_id=knowledge_id,
            top_k=top_k,
            policy_flags=policy_flags or {},
            style=style or "friendly",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        answer = chain.invoke({"question": question})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM 호출에 실패했습니다.") from exc

    sources = _build_sources(db, vector, knowledge_id, top_k)
    return QAResponse(
        answer=str(answer),
        question=question,
        session_id=session_id,
        sources=sources,
        documents=sources,
    )


@router.post("/chat/sessions/{session_id}/qa", response_model=QAResponse)
def ask_in_session(session_id: int, payload: ChatQARequest, db: Session = Depends(get_db)) -> QAResponse:
    _ensure_session(db, session_id)
    flags = {
        k: v
        for k, v in {
            "block_inappropriate": payload.block_inappropriate,
            "restrict_non_tech": payload.restrict_non_tech,
            "suggest_agent_handoff": payload.suggest_agent_handoff,
        }.items()
        if v is not None
    }
    return _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
        policy_flags=flags,
        style=payload.style,
    )


@router.post("/qa", response_model=QAResponse)
def ask_global(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    flags = {
        k: v
        for k, v in {
            "block_inappropriate": payload.block_inappropriate,
            "restrict_non_tech": payload.restrict_non_tech,
            "suggest_agent_handoff": payload.suggest_agent_handoff,
        }.items()
        if v is not None
    }
    session_id = payload.session_id
    if session_id is not None:
        _ensure_session(db, session_id)
    return _run_qa(
        db,
        question=payload.question,
        knowledge_id=payload.knowledge_id,
        top_k=payload.top_k,
        session_id=session_id,
        policy_flags=flags,
        style=payload.style,
    )


@router.post("/qa/query", response_model=QAResponse)
def ask_global_alias(payload: QARequest, db: Session = Depends(get_db)) -> QAResponse:
    return ask_global(payload, db)


############ STT 처리  ##############################
@router.post("/stt", response_model=STTResponse)
async def stt(file: UploadFile = File(...), lang: str = Form("ko-KR")):
    try:
        text = transcribe_bytes(await file.read(), file.content_type or "", lang)
        return STTResponse(text=text)
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")


@router.post("/stt_qa", response_model=QAResponse)
async def stt_qa(
    file: UploadFile = File(...),
    params: STTQAParams = Depends(STTQAParams.as_form),
    db: Session = Depends(get_db),
):
    try:
        # STT로 text 얻기
        text = transcribe_bytes(await file.read(), file.content_type or "", params.lang)
        flags = {
            k: v
            for k, v in {
                "block_inappropriate": params.block_inappropriate,
                "restrict_non_tech": params.restrict_non_tech,
                "suggest_agent_handoff": params.suggest_agent_handoff,
            }.items()
            if v is not None
        }
        return _run_qa(
            db,
            question=text,
            knowledge_id=params.knowledge_id,
            top_k=params.top_k,
            session_id=params.session_id,
            policy_flags=flags,
            style=params.style,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")


## Clova STT 활용 ##


def _ensure_wav_16k_mono(data: bytes, content_type: str) -> bytes:
    if content_type in ("audio/wav", "audio/x-wav"):
        return data
    if not shutil.which("ffmpeg"):
        return data  # ffmpeg 없으면 원본 전달
    with tempfile.NamedTemporaryFile(delete=False) as raw:
        raw.write(data)
        raw.flush()
        wav_path = raw.name + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw.name, "-ac", "1", "-ar", "16000", wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with open(wav_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(raw.name)
        except:
            pass
        try:
            os.remove(wav_path)
        except:
            pass


def _clova_transcribe(data: bytes, lang: str) -> str:
    if not CLOVA_STT_URL:
        raise RuntimeError("CLOVA_STT_URL 미설정")
    cid = os.getenv("CLOVA_STT_ID")
    csec = os.getenv("CLOVA_STT_SECRET")
    if not cid or not csec:
        raise RuntimeError("CLOVA_STT_ID/CLOVA_STT_SECRET 미설정")
    headers = {
        "X-NCP-APIGW-API-KEY-ID": cid,
        "X-NCP-APIGW-API-KEY": csec,
        "Content-Type": "application/octet-stream",
    }
    url = f"{CLOVA_STT_URL}?lang={lang or 'ko-KR'}"
    r = requests.post(url, headers=headers, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"clova stt {r.status_code}: {r.text[:200]}")
    text = r.json().get("text", "").strip()
    if not text:
        raise ValueError("empty transcription")
    return text


@router.post("/clova_stt", response_model=STTResponse)
async def clova_stt(file: UploadFile = File(...), lang: str = Form("ko-KR")):
    try:
        b = await file.read()
        wav = _ensure_wav_16k_mono(b, file.content_type or "")
        text = _clova_transcribe(wav, lang)
        return STTResponse(text=text)
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")


@router.post("/clova_stt_qa", response_model=QAResponse)
async def clova_stt_qa(
    file: UploadFile = File(...),
    params: STTQAParams = Depends(STTQAParams.as_form),
    db: Session = Depends(get_db),
):
    try:
        b = await file.read()
        wav = _ensure_wav_16k_mono(b, file.content_type or "")
        text = _clova_transcribe(wav, params.lang)
        flags = {
            k: v
            for k, v in {
                "block_inappropriate": params.block_inappropriate,
                "restrict_non_tech": params.restrict_non_tech,
                "suggest_agent_handoff": params.suggest_agent_handoff,
            }.items()
            if v is not None
        }
        return _run_qa(
            db,
            question=text,
            knowledge_id=params.knowledge_id,
            top_k=params.top_k,
            session_id=params.session_id,
            policy_flags=flags,
            style=params.style,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="empty transcription")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt failed: {e}")
