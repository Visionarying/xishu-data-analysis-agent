"""OpenAI 兼容大模型客户端。Key 只存在于服务端环境变量。"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MAX_TOKENS, LLM_MODEL, LLM_TIMEOUT_SECONDS, llm_configured


class LLMError(Exception):
    pass


def _endpoint() -> str:
    if LLM_BASE_URL.endswith("/chat/completions"):
        return LLM_BASE_URL
    return f"{LLM_BASE_URL}/chat/completions"


def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = LLM_MAX_TOKENS,
    timeout: float | None = None,
) -> str:
    if not llm_configured():
        raise LLMError("未配置大模型 API")

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout or LLM_TIMEOUT_SECONDS) as client:
            response = client.post(_endpoint(), headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise LLMError("模型响应超时") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"模型网络请求失败：{type(exc).__name__}") from exc

    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = body.get("error", {}).get("message", "") if isinstance(body, dict) else ""
        except ValueError:
            detail = response.text[:200]
        raise LLMError(f"模型接口返回 {response.status_code}：{detail or '请检查配置'}")

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("模型返回格式异常") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("模型返回内容为空")
    return content.strip()


def chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = LLM_MAX_TOKENS,
    timeout: float | None = None,
) -> Any:
    text = chat(system, user, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    return parse_json(text)


def parse_json(text: str) -> Any:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("模型未返回合法 JSON") from exc
    raise LLMError("模型未返回 JSON 对象")
