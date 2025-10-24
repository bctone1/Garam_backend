from langchain_openai import OpenAIEmbeddings
import core.config as config


def get_embeddings():
    return OpenAIEmbeddings(
        api_key = config.EMBEDDING_API,
        model=config.EMBEDDING_MODEL
     #    UPSTAGE 임베딩
     #    api_key = config.UPSTAGE_API,
     #    model = "embedding-query"
    )