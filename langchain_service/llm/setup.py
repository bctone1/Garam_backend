# langchain_service/llm/setup.py
import os
from langchain_openai import ChatOpenAI
import core.config as config
from pydantic import SecretStr


def _pick_key(*candidates):
    for key in candidates:
        if key:
            return key
    return None


def get_llm(
    provider: str = "openai",
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
    **kwargs,
):
    """
    LLM 인스턴스 생성기. streaming=True 전달 시 스트리밍 가능.
    """
    if provider == "openai":
        key = _pick_key(
            api_key,
            getattr(config, "OPENAI_API", None),
            getattr(config, "DEFAULT_API_KEY", None),
            os.getenv("OPENAI_API"),
        )
        if not key:
            raise RuntimeError("OPENAI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or config.DEFAULT_CHAT_MODEL,
            api_key=key,
            temperature=temperature,
            **kwargs,
        )

    elif provider in ("friendli", "lgai", "EXAONE"):
        key = _pick_key(
            api_key,
            getattr(config, "FRIENDLI_API", None),
            getattr(config, "FRIENDLI_TOKEN", None),
            os.getenv("FRIENDLI_API"),
            os.getenv("FRIENDLI_TOKEN"),
        )
        if not key:
            raise RuntimeError("Friendli API 키가 설정되지 않았습니다. FRIENDLI_API 또는 FRIENDLI_TOKEN을 설정하세요.")
        return ChatOpenAI(
            model=model or config.LLM_MODEL,   # endpoint_id
            api_key=key,
            base_url=config.FRIENDLI_BASE_URL,
            temperature=temperature,
            **kwargs,
        )

    else:
        raise ValueError(f"지원되지 않는 제공자: {provider}")


def get_backend_agent(
    provider: str = "openai",
    model: str | None = None,
    **kwargs,
):
    if provider == "openai":
        key = _pick_key(
            getattr(config, "EMBEDDING_API", None),
            getattr(config, "OPENAI_API", None),
            os.getenv("OPENAI_API"),
        )
        if not key:
            raise RuntimeError("EMBEDDING_API/OPENAI_API 키가 설정되지 않았습니다.")
        return ChatOpenAI(
            model=model or config.FRIENDLI_MODELS,
            api_key=key,
            temperature=0.7,
            **kwargs,
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
            **kwargs,
        )

    else:
        raise ValueError(f"지원되지 않는 제공자: {provider}")
