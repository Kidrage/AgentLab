"""Pure request/response adapters for supported native model APIs.

Network clients remain outside this module.  The deterministic seam makes the
four wire formats testable and gives every executor the same usage envelope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


SUPPORTED_NATIVE_PROTOCOLS = {
    "openai_chat",
    "openai_responses",
    "anthropic_messages",
    "gemini_generate_content",
}


@dataclass(frozen=True, slots=True)
class NativeRequest:
    protocol: str
    method: str
    path: str
    body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NativeResponse:
    protocol: str
    text: str
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cached_input_tokens: int | None
    finish_reason: str | None
    response_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        normalized.append({"role": role, "content": content})
    return normalized


def build_native_request(
    protocol: str,
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    max_output_tokens: int,
    temperature: float | None = None,
    top_p: float | None = None,
) -> NativeRequest:
    if protocol not in SUPPORTED_NATIVE_PROTOCOLS:
        raise ValueError(f"unsupported native protocol: {protocol}")
    normalized = _messages(messages)
    if protocol == "openai_chat":
        body: dict[str, Any] = {
            "model": model,
            "messages": normalized,
            "max_tokens": max_output_tokens,
        }
        path = "/v1/chat/completions"
    elif protocol == "openai_responses":
        body = {
            "model": model,
            "input": normalized,
            "max_output_tokens": max_output_tokens,
        }
        path = "/v1/responses"
    elif protocol == "anthropic_messages":
        systems = [item["content"] for item in normalized if item["role"] == "system"]
        body = {
            "model": model,
            "messages": [item for item in normalized if item["role"] != "system"],
            "max_tokens": max_output_tokens,
        }
        if systems:
            body["system"] = "\n\n".join(str(item) for item in systems)
        path = "/v1/messages"
    else:
        role_map = {"assistant": "model", "system": "user"}
        contents = []
        for item in normalized:
            content = item["content"]
            parts = content if isinstance(content, list) else [{"text": str(content)}]
            contents.append({"role": role_map.get(item["role"], item["role"]), "parts": parts})
        body = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_output_tokens},
        }
        path = f"/v1beta/models/{model}:generateContent"
    if temperature is not None:
        if protocol == "gemini_generate_content":
            body["generationConfig"]["temperature"] = temperature
        else:
            body["temperature"] = temperature
    if top_p is not None:
        if protocol == "gemini_generate_content":
            body["generationConfig"]["topP"] = top_p
        else:
            body["top_p"] = top_p
    return NativeRequest(protocol=protocol, method="POST", path=path, body=body)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_native_response(protocol: str, payload: Mapping[str, Any]) -> NativeResponse:
    if protocol not in SUPPORTED_NATIVE_PROTOCOLS:
        raise ValueError(f"unsupported native protocol: {protocol}")
    text = ""
    input_tokens = output_tokens = reasoning_tokens = cached_tokens = None
    finish_reason = response_id = None
    if protocol == "openai_chat":
        choices = payload.get("choices") or []
        choice = choices[0] if choices else {}
        text = str(((choice.get("message") or {}).get("content")) or "")
        finish_reason = choice.get("finish_reason")
        usage = payload.get("usage") or {}
        input_tokens = _int(usage.get("prompt_tokens"))
        output_tokens = _int(usage.get("completion_tokens"))
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = _int(details.get("reasoning_tokens"))
        cached_tokens = _int((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
        response_id = payload.get("id")
    elif protocol == "openai_responses":
        text = str(payload.get("output_text") or "")
        if not text:
            pieces = []
            for item in payload.get("output") or []:
                for content in item.get("content") or []:
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        pieces.append(str(content["text"]))
            text = "".join(pieces)
        usage = payload.get("usage") or {}
        input_tokens = _int(usage.get("input_tokens"))
        output_tokens = _int(usage.get("output_tokens"))
        reasoning_tokens = _int((usage.get("output_tokens_details") or {}).get("reasoning_tokens"))
        cached_tokens = _int((usage.get("input_tokens_details") or {}).get("cached_tokens"))
        finish_reason = payload.get("status")
        response_id = payload.get("id")
    elif protocol == "anthropic_messages":
        text = "".join(
            str(item.get("text") or "")
            for item in payload.get("content") or []
            if item.get("type") == "text"
        )
        usage = payload.get("usage") or {}
        input_tokens = _int(usage.get("input_tokens"))
        output_tokens = _int(usage.get("output_tokens"))
        cached_tokens = _int(usage.get("cache_read_input_tokens"))
        finish_reason = payload.get("stop_reason")
        response_id = payload.get("id")
    else:
        candidates = payload.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        text = "".join(
            str(item.get("text") or "")
            for item in ((candidate.get("content") or {}).get("parts") or [])
        )
        usage = payload.get("usageMetadata") or {}
        input_tokens = _int(usage.get("promptTokenCount"))
        output_tokens = _int(usage.get("candidatesTokenCount"))
        cached_tokens = _int(usage.get("cachedContentTokenCount"))
        reasoning_tokens = _int(usage.get("thoughtsTokenCount"))
        finish_reason = candidate.get("finishReason")
        response_id = payload.get("responseId")
    return NativeResponse(
        protocol=protocol,
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_input_tokens=cached_tokens,
        finish_reason=str(finish_reason) if finish_reason is not None else None,
        response_id=str(response_id) if response_id is not None else None,
    )
