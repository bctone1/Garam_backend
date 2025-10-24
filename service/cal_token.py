# pip install tiktoken sqlalchemy psycopg2-binary
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from models.knowledge import KnowledgeChunk  # 프로젝트 구조에 맞게 경로 조정
import tiktoken
from collections import defaultdict
import database.base as base

# 선택: 실제 사용한 임베딩 모델에 맞춰 설정
MODEL = "text-embedding-3-small"
PRICE_PER_1K = 0.02  # 달러/1K토큰. 실제 최신 단가로 교체

enc = tiktoken.encoding_for_model(MODEL)
engine = create_engine(base.DATABASE_URL, echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

tot_tokens = 0
per_kid_tokens = defaultdict(int)    # kid : Knowledge_id

with Session(engine) as s:    # s : sql alchemy session 객체
    q = s.query(KnowledgeChunk.knowledge_id, KnowledgeChunk.chunk_text).yield_per(1000)
    for kid, text in q:
        ntok = len(enc.encode(text or ""))
        per_kid_tokens[kid] += ntok
        tot_tokens += ntok

tot_cost = (tot_tokens / 1000.0) * PRICE_PER_1K

print({"total_tokens": tot_tokens, "total_cost_usd": round(tot_cost, 3)})
for kid, ntok in per_kid_tokens.items():
    print({"knowledge_id": kid, "tokens": ntok, "cost_usd": round((ntok/1000.0)*PRICE_PER_1K, 3)})
