import requests
import numpy as np
from typing import List
from langchain_core.embeddings import Embeddings
from langchain_service.embedding.setup import get_embeddings


def text_to_vector(text):
    embeddings = get_embeddings()
    try:
        vector = embeddings.embed_query(text)
        vector = np.array(vector)
        return vector
    except Exception as e:
        print(f"Error during embedding: {e}")
        return None


def _to_vector(question: str) -> list[float]:
    """임베딩 생성 + 변환 + 검증 래퍼 (APP/llm 및 runner에서 공통 사용)"""
    vector = text_to_vector(question)
    if vector is None:
        raise RuntimeError("임베딩 생성에 실패했습니다.")
    vector_list = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    if not vector_list:
        raise RuntimeError("임베딩 생성에 실패했습니다.")
    return [float(v) for v in vector_list]


# exaone 임베딩
class ExaoneEmbeddings(Embeddings):
    def __init__(self, api_url: str, api_key: str = None):
        self.api_url = api_url
        self.api_key = api_key

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(
            self.api_url,
            headers=headers,
            json={"texts": texts},
        )
        return response.json()["embeddings"]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]
