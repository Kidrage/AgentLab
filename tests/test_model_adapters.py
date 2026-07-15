from agent_runtime.model_adapters import build_native_request, parse_native_response


MESSAGES = [
    {"role": "system", "content": "be precise"},
    {"role": "user", "content": "hello"},
]


def test_native_request_shapes_are_protocol_specific():
    chat = build_native_request(
        "openai_chat", model="m", messages=MESSAGES, max_output_tokens=128
    )
    responses = build_native_request(
        "openai_responses", model="m", messages=MESSAGES, max_output_tokens=128
    )
    anthropic = build_native_request(
        "anthropic_messages", model="m", messages=MESSAGES, max_output_tokens=128
    )
    gemini = build_native_request(
        "gemini_generate_content", model="m", messages=MESSAGES, max_output_tokens=128
    )

    assert chat.path == "/v1/chat/completions" and "messages" in chat.body
    assert responses.path == "/v1/responses" and "input" in responses.body
    assert anthropic.path == "/v1/messages" and anthropic.body["system"] == "be precise"
    assert gemini.path.endswith(":generateContent") and "generationConfig" in gemini.body


def test_native_responses_share_one_usage_envelope():
    parsed = parse_native_response(
        "openai_responses",
        {
            "id": "resp_1",
            "status": "completed",
            "output_text": "ok",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "input_tokens_details": {"cached_tokens": 2},
                "output_tokens_details": {"reasoning_tokens": 1},
            },
        },
    )

    assert parsed.text == "ok"
    assert parsed.input_tokens == 10
    assert parsed.output_tokens == 4
    assert parsed.cached_input_tokens == 2
    assert parsed.reasoning_tokens == 1


def test_gemini_usage_metadata_is_normalized():
    parsed = parse_native_response(
        "gemini_generate_content",
        {
            "responseId": "g1",
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": "a"}, {"text": "b"}]},
            }],
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 3,
                "cachedContentTokenCount": 1,
                "thoughtsTokenCount": 2,
            },
        },
    )

    assert parsed.text == "ab"
    assert (parsed.input_tokens, parsed.output_tokens) == (8, 3)
    assert parsed.reasoning_tokens == 2
