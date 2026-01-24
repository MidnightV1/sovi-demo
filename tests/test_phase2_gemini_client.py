import types
from api_clients.gemini_client import GeminiClient, ModelConfig
from api_clients.exceptions import ApiConfigError


class FakeTransport:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    def stream_generate(self, payload: dict):
        # 简单返回给定chunk列表，模拟底层SDK的流式文本输出
        for c in self._chunks:
            yield c


def test_gemini_client_requires_transport():
    client = GeminiClient(transport=None)
    try:
        list(client.chat_with_streaming(messages=[{"role": "user", "content": "hi"}]))
        assert False, "should raise"
    except ApiConfigError:
        pass


def test_gemini_client_stream_and_completion():
    transport = FakeTransport(["<Sovi_Response>", "<Sovi_Response_Msg>Hi</Sovi_Response_Msg>", "</Sovi_Response>"])
    client = GeminiClient(transport=transport)

    events = list(client.chat_with_streaming(
        messages=[{"role": "user", "content": "hi"}],
        model_config=ModelConfig(max_output_tokens=16, temperature=0.1),
        system_prompt="SYS",
        client_request_id="rid-1",
    ))

    # 至少有若干 stream_chunk + 1 个 completion
    assert any(e.get('type') == 'stream_chunk' for e in events)
    assert events[-1]['type'] == 'completion'
    assert '</Sovi_Response>' in events[-1]['raw_response']


def test_message_builder_and_raw_helper_integration():
    class CollectingTransport(FakeTransport):
        def __init__(self, chunks, sink: list):
            super().__init__(chunks)
            self._sink = sink
        def stream_generate(self, payload: dict):
            # 将payload写入sink以供断言
            self._sink.append(payload)
            for c in self._chunks:
                yield c

    sink = []
    transport = CollectingTransport(["<Sovi_Response><Sovi_Response_Msg>OK</Sovi_Response_Msg></Sovi_Response>"], sink)
    client = GeminiClient(transport=transport)

    history = [{"role": "assistant", "content": "prev"}]
    list(client.chat_with_streaming_from_raw(
        user_input="hello",
        history=history,
        user_profile="CS freshman",
        client_datetime="2025-08-18 10:00",
        client_language="zh-CN",
        is_new_conversation=True,
    ))

    assert sink, "payload should be collected"
    payload = sink[0]
    msgs = payload["messages"]
    assert msgs[0]["role"] == "system"  # 默认系统提示词
    assert msgs[1] == history[0]
    assert msgs[-1]["role"] == "user"
    body = msgs[-1]["content"]
    # 新行为：上下文块通过 meta.blocks 传递，消息体仅包含原始用户文本
    meta = msgs[-1].get("meta", {})
    blocks = meta.get("blocks", {})
    assert "# User's Current Date and Time\n2025-08-18 10:00\n\n" == blocks.get("datetime")
    assert "# What You Know About the User\nCS freshman\n\n" == blocks.get("profile")
    assert meta.get("is_new_conversation") is True
    assert body.strip().endswith("hello")
