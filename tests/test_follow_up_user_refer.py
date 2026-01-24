import types
from api_clients.gemini_client import GeminiClient

class CollectingTransport:
    def __init__(self):
        self.payloads = []
        self._chunks = ["<Sovi_Response><Sovi_Response_Msg>OK</Sovi_Response_Msg></Sovi_Response>"]
    def stream_generate(self, payload: dict):
        # 收集 payload 用于断言
        self.payloads.append(payload)
        for c in self._chunks:
            yield c
    # 提供最小实现以配合客户端预构造 contents 与测试断言
    def _convert_messages_to_contents(self, messages: list):
        class SimplePart:
            def __init__(self, text: str):
                self.text = text
        class SimpleContent:
            def __init__(self, role: str, parts: list):
                self.role = role
                self.parts = parts
        contents = []
        for m in messages:
            role = m.get('role', 'user')
            if role == 'system':
                continue
            elif role in ['server', 'assistant']:
                role = 'model'
            meta = m.get('meta') or {}
            blocks = (meta.get('blocks') or {}) if isinstance(meta, dict) else {}
            has_blocks = bool(blocks.get('datetime') or blocks.get('profile') or blocks.get('user_refer'))
            text = m.get('content', '')
            if role == 'user' and has_blocks:
                prefix = f"{blocks.get('datetime','')}{blocks.get('profile','')}{blocks.get('user_refer','')}"
                if bool(meta.get('is_new_conversation')):
                    text = f"{prefix}<|server_command_begin|>\n{text}\n<|server_command_end|>"
                else:
                    if text.strip():
                        text = f"{prefix}<|user_text_begin|>\n{text}\n<|user_text_end|>"
                    else:
                        text = f"{prefix}<|user_text_begin|>\n\n<|user_text_end|>"
            contents.append(SimpleContent(role, [SimplePart(text)]))
        return contents


def test_user_refer_injected_into_blocks_and_prefix():
    transport = CollectingTransport()
    client = GeminiClient(transport=transport)

    # 通过 raw helper 传入 user_refer_text
    list(client.chat_with_streaming_from_raw(
        user_input="why?",
        history=[{"role":"assistant","content":"prev"}],
        user_profile="U",
        client_datetime="2025-08-19 10:00",
        client_language="zh-CN",
        user_refer_text="Selected quote",
    ))

    assert transport.payloads, "should capture payload"
    payload = transport.payloads[0]

    # messages 末条为当前用户消息
    msgs = payload["messages"]
    last = msgs[-1]
    meta = last.get("meta", {})
    blocks = meta.get("blocks", {})

    assert "# User's Current Date and Time" in blocks.get("datetime", "")
    assert "# What You Know About the User" in blocks.get("profile", "")
    # 新增：user_refer 块存在且包含 begin/end 标记与原文
    ur = blocks.get("user_refer", "")
    assert "<|user_refer_begin|>Selected quote<|user_refer_end|>\n\n" in ur

    # 传输层会在 _convert_messages_to_contents 中拼接 prefix，包括 user_refer
    # 这里直接调用同逻辑以验证拼接结果
    contents = client._transport._convert_messages_to_contents(msgs)  # noqa: SLF001
    user_content = next(c for c in contents if getattr(c, 'role', None) == 'user')
    # parts 最后一个为文本 part，包含我们需要的内容
    part_texts = [getattr(p, 'text', '') for p in getattr(user_content, 'parts', [])]
    text_joined = "\n".join(part_texts)
    assert "<|user_refer_begin|>Selected quote<|user_refer_end|>" in text_joined
