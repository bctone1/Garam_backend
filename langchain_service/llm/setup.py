# from langchain_google_genai import ChatGoogleGenerativeAI
import os
from langchain_openai import ChatOpenAI

import core.config as config
from pydantic import SecretStr

def _pick_key(*candidates):
    for key in candidates:
        if key:
            return key
    return None


def get_llm(provider: str = "openai", model: str | None = None,
            api_key: str | None = None, temperature: float = 0.7):
    if provider == "openai":
        key = _pick_key(api_key, getattr(config, "OPENAI_API", None),
                        getattr(config, "DEFAULT_API_KEY", None),
                        os.getenv("OPENAI_API_KEY"))
        if not key:
            raise RuntimeError("OPENAI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or config.DEFAULT_CHAT_MODEL,
            api_key=key,
            temperature=temperature,
        )

    elif provider in ("friendli", "lgai"):
        key = _pick_key(api_key, getattr(config, "FRIENDLI_API", None))
        if not key:
            raise RuntimeError("FRIENDLI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or config.FRIENDLI_MODELS,   # endpoint_id
            api_key=key,
            base_url=config.FRIENDLI_BASE_URL,
            temperature=temperature,
        )

    else:
        raise ValueError(f"지원되지 않는 제공자: {provider}")


def get_backend_agent(provider: str = "openai", model: str | None = None):
    if provider == "openai":
        key = _pick_key(getattr(config, "EMBEDDING_API", None),
                        getattr(config, "OPENAI_API", None),
                        os.getenv("OPENAI_API_KEY"))
        if not key:
            raise RuntimeError("EMBEDDING_API/OPENAI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or config.FRIENDLI_MODELS,
            api_key=key,
            temperature=0.7,
        )

    elif provider in ("friendli", "lgai"):
        key = getattr(config, "FRIENDLI_API", None)
        if not key:
            raise RuntimeError("FRIENDLI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or config.FRIENDLI_MODELS,
            api_key=key,
            base_url=config.FRIENDLI_BASE_URL,
            temperature=0.7,
        )

    else:
        raise ValueError(f"지원되지 않는 제공자: {provider}")