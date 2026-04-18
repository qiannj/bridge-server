"""Unit tests for SmartRouter and TaskDetector."""
import sys
from pathlib import Path
import pytest
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.services.routing.router import (
    TaskType,
    TaskDetector,
    RouteResult,
    RouterConfig,
    SmartRouter,
)


class TestTaskDetectorBasic:
    def setup_method(self):
        self.detector = TaskDetector()

    def test_empty_message_returns_general(self):
        task, conf = self.detector.detect("")
        assert task == TaskType.GENERAL
        assert conf == 0.5

    def test_coding_keyword_en_python(self):
        task, conf = self.detector.detect("write python code to sort a list")
        assert task == TaskType.CODING
        assert conf > 0.3

    def test_coding_keyword_en_debug(self):
        task, conf = self.detector.detect("debug this function please")
        assert task == TaskType.CODING

    def test_coding_keyword_cn(self):
        task, conf = self.detector.detect("帮我写代码实现排序算法")
        assert task == TaskType.CODING

    def test_writing_keyword_cn(self):
        task, conf = self.detector.detect("帮我写一篇文章介绍人工智能")
        assert task == TaskType.WRITING

    def test_writing_keyword_en(self):
        task, conf = self.detector.detect(
            "write an article about climate change for a science magazine"
        )
        assert task == TaskType.WRITING

    def test_analysis_keyword_cn(self):
        task, conf = self.detector.detect("分析这份数据报告的关键指标")
        assert task == TaskType.ANALYSIS

    def test_analysis_keyword_en(self):
        task, conf = self.detector.detect("analyze the quarterly sales data")
        assert task == TaskType.ANALYSIS

    def test_complex_keyword_cn(self):
        task, conf = self.detector.detect("请推理并证明这个数学定理")
        assert task == TaskType.COMPLEX

    def test_complex_keyword_en(self):
        # Avoid "this" which contains substring "hi" (SIMPLE keyword).
        task, conf = self.detector.detect("prove the mathematical theorem")
        assert task == TaskType.COMPLEX

    def test_simple_greeting_hello(self):
        task, conf = self.detector.detect("hello")
        assert task == TaskType.SIMPLE
        assert conf >= 0.5


class TestTaskDetectorExtractContent:
    def setup_method(self):
        self.detector = TaskDetector()

    def test_string_input_returned_unchanged(self):
        result = self.detector._extract_content("hello world")
        assert result == "hello world"

    def test_list_input_takes_last_message_content(self):
        messages = [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "last message"},
        ]
        result = self.detector._extract_content(messages)
        assert result == "last message"

    def test_dict_input_returns_content_field(self):
        result = self.detector._extract_content({"role": "user", "content": "test content"})
        assert result == "test content"

    def test_empty_list_falls_through_to_str(self):
        # Empty list skips the list branch (len==0) and falls through to str()
        result = self.detector._extract_content([])
        assert result == "[]"


class TestTaskDetectorWeights:
    def setup_method(self):
        self.detector = TaskDetector()

    def test_developer_domain_boosts_coding_over_writing(self):
        # "write some code" has equal coding/writing signals; developer context tips to CODING
        msg = "write some code for me"
        task_with_ctx, conf_with_ctx = self.detector.detect(
            msg, context={"user_domain": "developer"}
        )
        assert task_with_ctx == TaskType.CODING
        assert conf_with_ctx > 0.3

    def test_writer_domain_boosts_writing(self):
        task, conf = self.detector.detect(
            "write an article about science",
            context={"user_domain": "writer"},
        )
        assert task == TaskType.WRITING
        assert conf > 0.3

    def test_last_task_type_continuity_raises_confidence(self):
        # "write code" scores CODING=0.6 without context; continuity adds 0.1 → 0.7
        msg = "write code"
        _, conf_no_ctx = self.detector.detect(msg)
        _, conf_with_ctx = self.detector.detect(msg, context={"last_task_type": "coding"})
        assert conf_with_ctx > conf_no_ctx

    def test_short_text_boosts_simple(self):
        # "hi there" is < 20 chars; SIMPLE keyword + length boost → SIMPLE wins
        task, conf = self.detector.detect("hi there")
        assert task == TaskType.SIMPLE
        assert conf >= 0.3

    def test_long_text_boosts_complex(self):
        # >200 chars with COMPLEX keywords
        long_msg = (
            "prove this mathematical theorem "
            + "using detailed reasoning and logical steps " * 5
        )
        assert len(long_msg) > 200
        task, conf = self.detector.detect(long_msg)
        assert task == TaskType.COMPLEX
        assert conf >= 0.3


class TestRouteResult:
    def test_to_cache_from_cache_roundtrip_preserves_all_fields(self):
        original = RouteResult(
            provider_id="dashscope",
            model="qwen3-max",
            task_type=TaskType.CODING,
            confidence=0.9,
            reason="test reason",
            from_cache=False,
        )
        restored = RouteResult.from_cache(original.to_cache())

        assert restored.provider_id == original.provider_id
        assert restored.model == original.model
        assert restored.task_type == original.task_type
        assert restored.confidence == original.confidence
        assert restored.reason == original.reason

    def test_from_cache_sets_from_cache_true(self):
        data = {
            "provider_id": "openai",
            "model": "gpt-4",
            "task_type": "coding",
            "confidence": 0.8,
            "reason": "cached reason",
        }
        result = RouteResult.from_cache(data)
        assert result.from_cache is True

    def test_to_cache_dict_has_no_from_cache_key(self):
        result = RouteResult(
            provider_id="moonshot",
            model="moonshot-v1-8k",
            task_type=TaskType.GENERAL,
            confidence=0.5,
            reason="general task",
        )
        cached = result.to_cache()
        assert "from_cache" not in cached

    def test_to_cache_stores_task_type_as_string_value(self):
        result = RouteResult(
            provider_id="dashscope",
            model="qwen3.5-flash",
            task_type=TaskType.WRITING,
            confidence=0.7,
            reason="writing task",
        )
        cached = result.to_cache()
        assert isinstance(cached["task_type"], str)
        assert cached["task_type"] == "writing"


class TestSmartRouterNoCache:
    def _make_router(self):
        config = RouterConfig()
        config.cache_enabled = False
        return SmartRouter(config=config, cache=None)

    @pytest.mark.asyncio
    async def test_route_returns_route_result_instance(self):
        router = self._make_router()
        messages = [{"role": "user", "content": "Hello there"}]
        result = await router.route(messages)
        assert isinstance(result, RouteResult)

    @pytest.mark.asyncio
    async def test_route_with_provider_manager_selects_dashscope_model(self):
        router = self._make_router()
        messages = [{"role": "user", "content": "Hello"}]
        pm = SimpleNamespace(
            get_provider_models=lambda: {"dashscope": ["qwen3.5-flash", "qwen3-max"]}
        )
        result = await router.route(messages, provider_manager=pm)
        assert result.provider_id == "dashscope"
        assert result.model in ["qwen3.5-flash", "qwen3-max"]

    @pytest.mark.asyncio
    async def test_route_with_developer_context_gives_coding(self):
        router = self._make_router()
        # Has both writing ("write") and coding ("code") signals; developer domain tips to CODING
        messages = [{"role": "user", "content": "help me write some code"}]
        result = await router.route(messages, user_context={"user_domain": "developer"})
        assert result.task_type == TaskType.CODING

    @pytest.mark.asyncio
    async def test_empty_messages_uses_general(self):
        router = self._make_router()
        result = await router.route([])
        assert result.task_type == TaskType.GENERAL


class TestSmartRouterCacheKey:
    def setup_method(self):
        config = RouterConfig()
        self.router = SmartRouter(config=config)

    def test_same_message_produces_same_key(self):
        key1 = self.router._generate_cache_key("hello world")
        key2 = self.router._generate_cache_key("hello world")
        assert key1 == key2

    def test_different_messages_produce_different_keys(self):
        key1 = self.router._generate_cache_key("message one about coding")
        key2 = self.router._generate_cache_key("message two about writing")
        assert key1 != key2

    def test_context_affects_cache_key(self):
        msg = "write some code"
        key_no_ctx = self.router._generate_cache_key(msg)
        key_with_ctx = self.router._generate_cache_key(
            msg, context={"user_domain": "developer"}
        )
        assert key_no_ctx != key_with_ctx
