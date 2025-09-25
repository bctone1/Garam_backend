import os
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from crud import knowledge as crud_knowledge
from service.prompt import pdf_preview_prompt

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_service.embedding.get_vector import text_to_vector

import core.config as config


async def upload_knowledge_file(db: Session, file: UploadFile, user_id: str):
    """
    파일 업로드 → PDF 요약 → 벡터화 → DB 저장 전체 파이프라인
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

    # 4. knowledge 테이블에 메타데이터 저장
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

    # 5. PDF → Document → Chunk 나누기
    loader = PyMuPDFLoader(file_path)
    documents = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    split_docs = splitter.split_documents(documents)

    # 6. 각 청크 벡터화 후 knowledge_chunk에 저장
    chunk_payload = []
    for idx, doc in enumerate(split_docs):
        vector = text_to_vector(doc.page_content)
        if vector is None:
            continue
        chunk_payload.append({
            "index": idx,
            "text": doc.page_content,
            "vector": vector,
        })

    if chunk_payload:
        crud_knowledge.create_knowledge_chunks(db, knowledge.id, chunk_payload)

    return knowledge


def get_file_by_id(db: Session, file_id: int, user_id: int):
    """
    저장된 파일 경로를 반환 (존재 확인 포함)
    """
    file_path = crud_knowledge.get_knowledge_by_id(db, file_id, user_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일이 존재하지 않습니다")
    return file_path
