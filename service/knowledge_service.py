# services/knowledge_service.py
import os
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from datetime import datetime, timezone
import logging

from crud import knowledge as crud_knowledge
from crud import api_cost as cost
from service.prompt import pdf_preview_prompt

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_service.embedding.get_vector import text_to_vector

from core import config
from core.pricing import normalize_usage_embedding, estimate_embedding_cost_usd

log = logging.getLogger("api_cost")

# 토큰 길이 함수: tiktoken 있으면 사용, 없으면 문자 길이
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def _tok_len(s: str) -> int:
        return len(_enc.encode(s or ""))
except Exception:
    def _tok_len(s: str) -> int:
        return len(s or "")


async def upload_knowledge_file(db: Session, file: UploadFile, user_id: str):
    """
    파일 업로드 → PDF 요약 → 벡터화 → DB 저장 → 비용 집계
    """
    # 1. 사용자별 디렉토리 생성
    save_dir = config.UPLOAD_FOLDER
    user_dir = os.path.join(save_dir, str(user_id), "document")
    os.makedirs(user_dir, exist_ok=True)

    # 2. 파일 저장
    origin_name = file.filename
    random_suffix = uuid4().hex[:8]
    file_name = f"{user_id}_{random_suffix}_{origin_name}"
    file_path = os.path.join(user_dir, file_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    file_type = file.content_type
    file_size = len(content)

    # 3. PDF 미리보기 및 태그 추출
    pdf_preview = pdf_preview_prompt(file_path)
    tags = pdf_preview.get("tags", "")
    preview = pdf_preview.get("preview", [])

    # 4. knowledge 메타 저장
    knowledge = crud_knowledge.create_knowledge(
        db=db,
        origin_name=origin_name,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        user_id=user_id,
        tags=tags,
        preview=preview,
    )

    # 5. PDF → Document → Chunk
    loader = PyMuPDFLoader(file_path)
    documents = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=250)
    split_docs = splitter.split_documents(documents)

    # 6. 청크 임베딩 및 저장 + 토큰 합산
    chunk_payload = []
    total_tokens = 0
    for idx, doc in enumerate(split_docs):
        text = doc.page_content or ""
        total_tokens += _tok_len(text)
        vec = text_to_vector(text)
        if vec is None:
            continue
        chunk_payload.append({
            "index": idx,
            "text": text,
            "vector": vec,
        })

    if chunk_payload:
        crud_knowledge.create_knowledge_chunks(db, knowledge.id, chunk_payload)

        # 7. 비용 집계: 임베딩
        try:
            usage = normalize_usage_embedding(total_tokens)
            usd = estimate_embedding_cost_usd(
                model=getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
                total_tokens=usage["embedding_tokens"],
            )
            cost.add_event(
                db,
                ts_utc=datetime.now(timezone.utc),
                product="embedding",
                model=getattr(config, "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
                llm_tokens=0,
                embedding_tokens=usage["embedding_tokens"],
                audio_seconds=0,
                cost_usd=usd,
            )
        except Exception as e:
            log.exception("api-cost embedding record failed: %s", e)

    return knowledge


def get_file_by_id(db: Session, file_id: int, user_id: int):
    """
    저장된 파일 경로를 반환 (존재 확인 포함)
    """
    file_path = crud_knowledge.get_knowledge_by_id(db, file_id, user_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일이 존재하지 않습니다")
    return file_path
