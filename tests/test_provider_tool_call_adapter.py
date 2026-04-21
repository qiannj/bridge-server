from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from conftest import SRC_DIR

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

openai_mod = importlib.import_module("bridge_server.providers.openai")
OpenAIProvider = openai_mod.OpenAIProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_openai_provider_preserves_tool_payload_fields():
    provider = OpenAIProvider({"id": "openai", "api_key": "test-key", "base_url": "https://example.com"})

    captured = {}

    async def _fake_post(path, json):
        captured["path"] = path
        captured["json"] = json
        return _FakeResponse({
            "id": "resp_1",
            "model": "gpt-4",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "done"},
                "finish_reason": "stop",
            }],
            "usage": {},
        })

    provider.client = SimpleNamespace(post=_fake_post)

    upstream_tool_call = {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "exec",
            "arguments": '{"command":"pwd"}',
        },
    }

    response = await provider._make_request(
        messages=[
            {"role": "user", "content": "请帮我看一下目录"},
            {"role": "assistant", "content": None, "tool_calls": [upstream_tool_call]},
            {"role": "tool", "tool_call_id": "call_123", "content": "{}"},
        ],
        model="gpt-4",
        max_tokens=256,
        tools=[{
            "type": "function",
            "function": {
                "name": "exec",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }],
        tool_choice={"type": "function", "function": {"name": "exec"}},
        parallel_tool_calls=True,
    )

    assert response["provider"] == "openai"
    assert captured["path"] == "/chat/completions"
    assert captured["json"]["tools"][0]["function"]["name"] == "exec"
    assert captured["json"]["tool_choice"]["function"]["name"] == "exec"
    assert captured["json"]["parallel_tool_calls"] is True
    assert captured["json"]["messages"][1]["tool_calls"][0]["function"]["name"] == "exec"
    assert captured["json"]["messages"][2]["tool_call_id"] == "call_123"


@pytest.mark.asyncio
async def test_openai_provider_converts_tagged_tool_call_content_to_openai_tool_calls():
    provider = OpenAIProvider({"id": "openai", "api_key": "test-key", "base_url": "https://example.com"})

    async def _fake_post(path, json):
        return _FakeResponse({
            "id": "resp_2",
            "model": "minimax-m2.7",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "我先看下之前的账本格式和 [current.md](current.md) 在哪儿，找到了再更新。\n<minimax:tool_call>\n<invoke name=\"exec\">\n<parameter name=\"command\">find . -name current.md</parameter>\n</invoke>\n</minimax:tool_call>",
                },
                "finish_reason": "stop",
            }],
            "usage": {},
        })

    provider.client = SimpleNamespace(post=_fake_post)

    response = await provider._make_request(
        messages=[{"role": "user", "content": "更新 current.md"}],
        model="gpt-4",
    )

    choice = response["choices"][0]
    message = choice["message"]

    assert choice["finish_reason"] == "tool_calls"
    assert message["content"] == "我先看下之前的账本格式和 [current.md](current.md) 在哪儿，找到了再更新。"
    assert message["tool_calls"][0]["function"]["name"] == "exec"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"command": "find . -name current.md"}'


@pytest.mark.asyncio
async def test_openai_provider_converts_tool_code_blocks_to_openai_tool_calls():
    provider = OpenAIProvider({"id": "openai", "api_key": "***", "base_url": "https://example.com"})

    async def _fake_post(path, json):
        return _FakeResponse({
            "id": "resp_3",
            "model": "minimax-m2.7",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "我来帮你排查项目文档 `current.md`。按照你的要求，我需要逐步进行：\n\n**步骤 1：搜索文件位置**\n<tool_code>\n{\n  tool => 'workspace_search_files',\n  args => '\n<query>current.md</query>\n'\n}\n</tool_code>",
                },
                "finish_reason": "stop",
            }],
            "usage": {},
        })

    provider.client = SimpleNamespace(post=_fake_post)

    response = await provider._make_request(
        messages=[{"role": "user", "content": "排查 current.md"}],
        model="gpt-4",
    )

    choice = response["choices"][0]
    message = choice["message"]

    assert choice["finish_reason"] == "tool_calls"
    assert message["content"] == "我来帮你排查项目文档 `current.md`。按照你的要求，我需要逐步进行：\n\n**步骤 1：搜索文件位置**"
    assert message["tool_calls"][0]["function"]["name"] == "workspace_search_files"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"query": "current.md"}'


@pytest.mark.asyncio
async def test_openai_provider_converts_tool_name_param_blocks_to_openai_tool_calls():
    provider = OpenAIProvider({"id": "openai", "api_key": "***", "base_url": "https://example.com"})

    async def _fake_post(path, json):
        return _FakeResponse({
            "id": "resp_4",
            "model": "minimax-m2.7",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "我来帮你排查项目文档 current.md。按照你的要求，我需要先搜索它的位置。\n\n让我先搜索这个文件：\n<tool_call>\n<tool name=\"search_files\">\n<param name=\"path\">.</param>\n\n<param name=\"pattern\">current.md</param>\n\n</tool>\n</tool_call>",
                },
                "finish_reason": "stop",
            }],
            "usage": {},
        })

    provider.client = SimpleNamespace(post=_fake_post)

    response = await provider._make_request(
        messages=[{"role": "user", "content": "排查 current.md"}],
        model="gpt-4",
    )

    choice = response["choices"][0]
    message = choice["message"]

    assert choice["finish_reason"] == "tool_calls"
    assert message["content"] == "我来帮你排查项目文档 current.md。按照你的要求，我需要先搜索它的位置。\n\n让我先搜索这个文件："
    assert message["tool_calls"][0]["function"]["name"] == "search_files"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"path": ".", "pattern": "current.md"}'
