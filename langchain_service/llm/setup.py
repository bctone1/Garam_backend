# from langchain_google_genai import ChatGoogleGenerativeAI
import os
from langchain_openai import ChatOpenAI

import core.config as config
from pydantic import SecretStr


# 테스트용 openai 와 실제 서비스는 Exaone 이용
DEFAULT_MODEL = getattr(config, "DEFAULT_CHAT_MODEL", "gpt-4o-mini")
FRIENDLI_MODEL = "LGAI-EXAONE/EXAONE-4.0.1-32B"
FRIENDLI_BASE = "https://api.friendli.ai/serverless/v1"


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
            model=model or DEFAULT_MODEL,
            api_key=key,
            temperature=temperature,
        )

    elif provider in ("friendli", "lgai"):
        key = _pick_key(api_key, getattr(config, "FRIENDLI_API", None))
        if not key:
            raise RuntimeError("FRIENDLI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or FRIENDLI_MODEL,   # endpoint_id
            api_key=key,
            base_url=FRIENDLI_BASE,
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
            model=model or DEFAULT_MODEL,
            api_key=key,
            temperature=0.7,
        )

    elif provider in ("friendli", "lgai"):
        key = getattr(config, "FRIENDLI_API", None)
        if not key:
            raise RuntimeError("FRIENDLI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or FRIENDLI_MODEL,
            api_key=key,
            base_url=FRIENDLI_BASE,
            temperature=0.7,
        )

    else:
        raise ValueError(f"지원되지 않는 제공자: {provider}")