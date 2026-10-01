# -*- coding: utf-8 -*-
"""
LLM 客户端 — OpenAI 兼容 /chat/completions（kline-page-change design D5/D8.1）。

仅依赖 requests（不引入 openai/httpx SDK）。
- complete(system, prompt, timeout) -> str            非流式，供测试连接与内部调用
- complete_stream(system, prompt, timeout) -> Iterator[str]   流式增量，ask SSE 消费

config 参数可选（扩展自 design 的 3 参签名）：传入 {base_url, api_key, model} 可指定
预设/临时配置（测试连接的 id/字段分支）；缺省走 llm_store.resolve_llm_config() 三层解析。
timeout 用 requests 的 timeout=(5, N) 传入，N 为读超时（流式时即块间空闲超时），
底层读超时/连接失败视为中断，抛 LLMError 交给上层发 error 事件。
"""

import json
from typing import Any, Iterator, Optional

import requests

from .llm_store import resolve_llm_config


class LLMError(Exception):
    """LLM 调用失败（含供应商错误原文）。"""


def _require_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    """取调用配置：显式 config 优先，否则走三层解析；均无抛 LLMError。"""
    if config is not None:
        return config
    resolved = resolve_llm_config()
    if resolved is None:
        raise LLMError("LLM 未配置")
    return resolved


def _chat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _messages(system: str, prompt: str) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def _post(cfg: dict[str, Any], payload: dict[str, Any], timeout: float, stream: bool):
    """发起 /chat/completions 请求，HTTP 非 200 / 网络失败抛 LLMError。"""
    try:
        resp = requests.post(
            _chat_url(cfg["base_url"]),
            json=payload,
            headers=_headers(cfg.get("api_key", "")),
            timeout=(5, timeout),
            stream=stream,
        )
    except requests.RequestException as e:
        raise LLMError(f"LLM 请求失败: {e}") from e
    if resp.status_code != 200:
        detail = resp.text[:500]
        resp.close()
        raise LLMError(f"LLM 返回 HTTP {resp.status_code}: {detail}")
    # SSE/JSON 均为 UTF-8；requests 对 text/* 默认 ISO-8859-1，需显式指定
    resp.encoding = "utf-8"
    return resp


def complete(
    system: str,
    prompt: str,
    timeout: float,
    config: Optional[dict[str, Any]] = None,
) -> str:
    """非流式补全，返回完整回答文本。"""
    cfg = _require_config(config)
    payload = {
        "model": cfg["model"],
        "messages": _messages(system, prompt),
        "stream": False,
    }
    resp = _post(cfg, payload, timeout, stream=False)
    try:
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        raise LLMError(f"LLM 响应解析失败: {e}") from e
    finally:
        resp.close()


def complete_stream(
    system: str,
    prompt: str,
    timeout: float,
    config: Optional[dict[str, Any]] = None,
) -> Iterator[str]:
    """流式补全，逐段 yield 增量文本（OpenAI 兼容 SSE：data: {...} / data: [DONE]）。"""
    cfg = _require_config(config)
    payload = {
        "model": cfg["model"],
        "messages": _messages(system, prompt),
        "stream": True,
    }
    resp = _post(cfg, payload, timeout, stream=True)
    try:
        # chunk_size=1：小增量不被 512 默认缓冲卡住（close-delimited 响应下 read(amt)
        # 会阻塞到攒满 amt 字节），保证「边生成边发」的实时性
        for line in resp.iter_lines(chunk_size=1, decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content")
            if text:
                yield text
    except requests.RequestException as e:
        # 读超时/连接中断：视为生成中断，交给上层发 error
        raise LLMError(f"LLM 流式中断: {e}") from e
    finally:
        resp.close()
