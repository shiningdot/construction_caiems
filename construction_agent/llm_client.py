"""统一 LLM 客户端：Anthropic 协议 / OpenAI 兼容协议（硅基流动）。

项目里的调用点全部按 Anthropic Messages API 的形状编写：

    response = client.messages.create(
        model=..., max_tokens=..., system=..., tools=[...], messages=[...])
    response.content  -> [block(type="text" | "tool_use" | "thinking"), ...]
    response.usage    -> .input_tokens / .output_tokens

本模块提供 ``create_llm_client()``：

- ``LLM_PROVIDER=anthropic``（默认）：原样返回 ``anthropic.Anthropic``
- ``LLM_PROVIDER=siliconflow``：返回 ``OpenAICompatClient``，把同样的调用
  翻译成 OpenAI Chat Completions，再把响应翻译回同样的形状。
- ``LLM_PROVIDER=ark``：火山方舟（OpenAI 兼容端点），同样走
  ``OpenAICompatClient``；仅供批量任务使用（按未命中缓存计价，见 .env 注释）。

这样切换供应商只需要改 ``.env`` 一行，所有调用点无需感知协议差异。
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from construction_agent.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_ALIASES = {"anthropic", "claude", "deepseek"}
SILICONFLOW_ALIASES = {"siliconflow", "openai", "openai-compatible", "sf"}
ARK_ALIASES = {"ark", "volcengine", "volces", "火山方舟"}


# ══════════════════════════════════════════════════════════════════
# 供应商解析
# ══════════════════════════════════════════════════════════════════

def active_provider(provider: Optional[str] = None) -> str:
    """返回规范化的供应商名：``anthropic`` / ``siliconflow`` / ``ark``。"""
    raw = (provider or getattr(settings, "LLM_PROVIDER", "anthropic") or "anthropic")
    raw = raw.strip().lower()
    if raw in ARK_ALIASES:
        return "ark"
    if raw in SILICONFLOW_ALIASES:
        return "siliconflow"
    if raw in ANTHROPIC_ALIASES:
        return "anthropic"
    logger.warning("未知 LLM_PROVIDER=%r，回退 anthropic", raw)
    return "anthropic"


def resolve_model(provider: Optional[str] = None) -> str:
    """当前供应商下应使用的模型 ID。"""
    prov = active_provider(provider)
    if prov == "siliconflow":
        return settings.SILICONFLOW_MODEL
    if prov == "ark":
        return settings.ARK_MODEL
    return settings.ANTHROPIC_MODEL


def resolve_max_tokens(provider: Optional[str] = None) -> int:
    """当前供应商下的默认输出预算。

    硅基流动上的推理模型会先花掉一部分预算写思维链，4096 容易返回空文本，
    因此单独给一个更大的默认值（``SILICONFLOW_MAX_TOKENS``，默认 16384）。
    """
    prov = active_provider(provider)
    if prov == "siliconflow":
        return getattr(settings, "SILICONFLOW_MAX_TOKENS", 16384)
    if prov == "ark":
        return getattr(settings, "ARK_MAX_TOKENS", 16384)
    return settings.ANTHROPIC_MAX_TOKENS


def create_llm_client(
    api_key: Optional[str] = None,
    *,
    provider: Optional[str] = None,
):
    """按 ``LLM_PROVIDER`` 创建客户端；缺 key 时返回 ``None``。

    返回对象的 ``messages.create(...)`` 接口与 Anthropic SDK 同形，
    并额外暴露 ``model`` / ``default_max_tokens`` 供调用点读取。
    """
    prov = active_provider(provider)
    if prov == "siliconflow":
        key = api_key or settings.SILICONFLOW_API_KEY
        if not key:
            logger.warning("SILICONFLOW_API_KEY 未配置，LLM 客户端不可用")
            return None
        return OpenAICompatClient(key, settings.SILICONFLOW_BASE_URL)

    if prov == "ark":
        key = api_key or settings.ARK_API_KEY
        if not key:
            logger.warning("ARK_API_KEY 未配置，LLM 客户端不可用")
            return None
        return OpenAICompatClient(
            key,
            settings.ARK_BASE_URL,
            model=settings.ARK_MODEL,
            default_max_tokens=getattr(settings, "ARK_MAX_TOKENS", 16384),
        )

    key = api_key or settings.ANTHROPIC_API_KEY
    if not key:
        logger.warning("ANTHROPIC_API_KEY 未配置，LLM 客户端不可用")
        return None

    from anthropic import Anthropic
    return Anthropic(api_key=key, base_url=settings.ANTHROPIC_BASE_URL)


# ══════════════════════════════════════════════════════════════════
# Anthropic 风格 → OpenAI 兼容
# ══════════════════════════════════════════════════════════════════

def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _blocks(content: Any) -> Iterable[Any]:
    """把 message content 统一成可迭代的 block 序列。"""
    if content is None:
        return []
    if isinstance(content, str):
        return [SimpleNamespace(type="text", text=content)]
    if isinstance(content, (list, tuple)):
        return content
    return [content]


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    text = _attr(block, "text")
    return text if isinstance(text, str) else ""


def _content_text(content: Any) -> str:
    return "".join(_block_text(b) for b in _blocks(content))


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    return _content_text(system)


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return _content_text(content)
    return str(content or "")


def _convert_messages(messages: list[dict], system: Any) -> list[dict]:
    """Anthropic messages → OpenAI messages。"""
    out: list[dict] = []
    if system:
        sys_text = _system_text(system)
        if sys_text.strip():
            out.append({"role": "system", "content": sys_text})

    for message in messages or []:
        role = _attr(message, "role", "user")
        content = _attr(message, "content")

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in _blocks(content):
                btype = _attr(block, "type")
                if btype == "tool_use":
                    tool_calls.append({
                        "id": _attr(block, "id") or f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": _attr(block, "name"),
                            "arguments": json.dumps(
                                _attr(block, "input") or {}, ensure_ascii=False),
                        },
                    })
                elif btype in (None, "text"):
                    text_parts.append(_block_text(block))
                # thinking 块不回传：OpenAI 兼容端点不接受

            item: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(text_parts) or None,
            }
            if tool_calls:
                item["tool_calls"] = tool_calls
            out.append(item)
            continue

        # user：可能同时包含普通文本与 tool_result
        text_parts = []
        tool_results: list[dict] = []
        for block in _blocks(content):
            btype = _attr(block, "type")
            if btype == "tool_result":
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": _attr(block, "tool_use_id") or _attr(block, "id"),
                    "content": _tool_result_text(_attr(block, "content")),
                })
            elif btype in (None, "text"):
                text_parts.append(_block_text(block))

        if text_parts:
            out.append({"role": "user", "content": "".join(text_parts)})
        out.extend(tool_results)

    return out


def _convert_tools(tools: Optional[list]) -> Optional[list[dict]]:
    """Anthropic tool schema → OpenAI function schema。"""
    if not tools:
        return None
    converted = []
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "function":
            converted.append(tool)  # 已经是 OpenAI 格式
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": _attr(tool, "name"),
                "description": _attr(tool, "description", "") or "",
                "parameters": (
                    _attr(tool, "input_schema")
                    or _attr(tool, "parameters")
                    or {"type": "object", "properties": {}}
                ),
            },
        })
    return converted or None


def _convert_tool_choice(choice: Any) -> Any:
    if choice is None or isinstance(choice, str):
        return choice
    ctype = _attr(choice, "type")
    if ctype == "auto":
        return "auto"
    if ctype == "any":
        return "required"
    if ctype == "none":
        return "none"
    if ctype == "tool":
        name = _attr(choice, "name")
        return {"type": "function", "function": {"name": name}}
    return None


def _convert_response(response: Any, fallback_model: str) -> Any:
    """OpenAI ChatCompletion → Anthropic Messages 形状。"""
    choice = (getattr(response, "choices", None) or [None])[0]
    message = getattr(choice, "message", None) if choice else None

    blocks: list[Any] = []
    reasoning = getattr(message, "reasoning_content", None) if message else None
    if reasoning:
        blocks.append(SimpleNamespace(type="thinking", thinking=reasoning))

    text = getattr(message, "content", None) if message else None
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))

    for call in (getattr(message, "tool_calls", None) or []):
        function = getattr(call, "function", None)
        raw_args = getattr(function, "arguments", "") or "{}"
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            args = {"_raw": raw_args}
        blocks.append(SimpleNamespace(
            type="tool_use",
            id=getattr(call, "id", None),
            name=getattr(function, "name", None),
            input=args,
        ))

    if not blocks:
        blocks.append(SimpleNamespace(type="text", text=""))

    usage = getattr(response, "usage", None)
    return SimpleNamespace(
        content=blocks,
        usage=SimpleNamespace(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        ),
        model=getattr(response, "model", None) or fallback_model,
        stop_reason=getattr(choice, "finish_reason", None) if choice else None,
        raw=response,
    )


class _MessagesProxy:
    """``client.messages.create`` 的适配层。"""

    def __init__(self, owner: "OpenAICompatClient"):
        self._owner = owner

    def create(
        self,
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        system: Any = None,
        messages: Optional[list[dict]] = None,
        tools: Optional[list] = None,
        tool_choice: Any = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop_sequences: Optional[list[str]] = None,
        timeout: Optional[float] = None,
        stream: bool = False,
        **extra: Any,
    ) -> Any:
        if stream:
            raise NotImplementedError("OpenAICompatClient 暂不支持 stream=True")

        resolved_model = model or self._owner.model
        body: dict[str, Any] = {
            "model": resolved_model,
            "messages": _convert_messages(messages or [], system),
            "max_tokens": int(max_tokens or self._owner.default_max_tokens),
        }
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if stop_sequences:
            body["stop"] = stop_sequences

        openai_tools = _convert_tools(tools)
        if openai_tools:
            body["tools"] = openai_tools
            converted_choice = _convert_tool_choice(tool_choice)
            if converted_choice is not None:
                body["tool_choice"] = converted_choice

        # 未知的 Anthropic 专有参数（thinking / metadata 等）直接忽略。
        ignored = sorted(set(extra) - {"top_k"})
        if ignored:
            logger.debug("OpenAI 兼容模式忽略参数: %s", ignored)

        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if self._owner.default_extra:
            kwargs["extra_body"] = dict(self._owner.default_extra)

        response = self._owner._client.chat.completions.create(**body, **kwargs)
        return _convert_response(response, resolved_model)


class OpenAICompatClient:
    """把 OpenAI 兼容端点包装成 Anthropic Messages 客户端。

    只有 ``messages.create`` 是项目实际用到的接口；``model`` 与
    ``default_max_tokens`` 供调用点读取默认值。
    """

    def __init__(self, api_key: str, base_url: str, *, client: Any = None,
                 model: Optional[str] = None,
                 default_max_tokens: Optional[int] = None,
                 timeout: float = 180.0,
                 default_extra: Optional[dict] = None):
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._client = client
        self.base_url = base_url
        # 附加到每个 chat/completions 请求的字段（如 Ark 的 thinking 开关）
        self.default_extra = dict(default_extra or {})
        # 默认沿用硅基流动配置以保持既有调用点行为；ark 等其它端点显式传入。
        self.model = model or settings.SILICONFLOW_MODEL
        self.default_max_tokens = (
            default_max_tokens if default_max_tokens is not None
            else resolve_max_tokens("siliconflow"))
        self.messages = _MessagesProxy(self)
