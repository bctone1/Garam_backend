from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from core.tools import fit_anthropic_model
import core.config as config
from pydantic import SecretStr
from openai import OpenAI
import os


def get_llm(provider="openai", model = None, api_key : str = None, temperature = 0.7):
    if provider == "openai":
        model_name = model or config.DEFAULT_CHAT_MODEL
        return ChatOpenAI(
            api_key = api_key,
            model_name=model_name,
            temperature = temperature
        )
    elif provider == "anthropic":
        model_name = model or "claude-3-sonnet-20240229"
        model_name = fit_anthropic_model(model_name=model_name)
        return ChatAnthropic(
            anthropic_api_key = SecretStr(api_key or ""),
            model = model_name,
            temperature = temperature
        )
    elif provider == "google":
        model_name = model or  "gemini-2.5-pro"
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key = config.GOOGLE_API,
            temperature=temperature
        )


    elif provider in ("friendli", "lgai"):
        model_name = model or "LGAI-EXAONE/EXAONE-4.0.1-32B"
        return ChatOpenAI(
            api_key=config.FRIENDLI_API,
            model =model_name ,  # (endpoint_id)
            base_url="https://api.friendli.ai/serverless/v1",
            temperature=temperature
        )
    else:
        raise ValueError(f"지원되지 않는 제공자: {provider}")


def get_backend_agent(provider="openai", model=None):
    if provider == "openai":
        model_name = model or config.DEFAULT_CHAT_MODEL
        return ChatOpenAI(
            openai_api_key=config.EMBEDDING_API,
            model_name=model_name,
            temperature=0.7
        )

