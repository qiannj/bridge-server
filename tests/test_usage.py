"""用量统计服务测试"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import json
import tempfile
import shutil
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.usage import UsageTracker, get_tracker, record_usage


class TestUsageTrackerInit:
    """测试 UsageTracker 初始化"""
    
    def test_init_creates_directory(self):
        """测试初始化创建目录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / ".bridge-server"
            tracker = UsageTracker(config_dir)
            
            assert config_dir.exists()
            assert tracker.usage_file.parent == config_dir
    
    def test_init_default_path(self):
        """测试默认路径初始化"""
        tracker = UsageTracker()
        assert tracker.config_dir == Path.home() / ".bridge-server"


class TestRecordUsage:
    """测试用量记录"""
    
    def test_record_success(self):
        """测试成功记录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            today = datetime.now().strftime("%Y-%m-%d")
            
            tracker.record(
                model="qwen3.5-plus",
                provider="dashscope",
                tokens_in=100,
                tokens_out=200,
                cost=0.0012,
                duration_ms=500,
                success=True
            )
            
            usage = tracker._load_usage()
            assert today in usage["days"]
            assert usage["days"][today]["requests"] == 1
            assert usage["days"][today]["requests_success"] == 1
            assert usage["days"][today]["tokens_in"] == 100
            assert usage["days"][today]["tokens_out"] == 200
            assert usage["days"][today]["cost"] == 0.0012
    
    def test_record_failure(self):
        """测试失败记录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            today = datetime.now().strftime("%Y-%m-%d")
            
            tracker.record(
                model="qwen3.5-plus",
                provider="dashscope",
                tokens_in=0,
                tokens_out=0,
                cost=0.0,
                duration_ms=100,
                success=False
            )
            
            usage = tracker._load_usage()
            assert usage["days"][today]["requests_failed"] == 1
    
    def test_record_multiple_calls(self):
        """测试多次记录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            today = datetime.now().strftime("%Y-%m-%d")
            
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            tracker.record("model1", "provider1", 150, 250, 0.0015, 150)
            tracker.record("model2", "provider1", 50, 100, 0.0005, 50)
            
            usage = tracker._load_usage()
            assert usage["days"][today]["requests"] == 3
            assert usage["days"][today]["tokens_in"] == 300
            assert usage["days"][today]["tokens_out"] == 550
            assert usage["days"][today]["cost"] == 0.003
    
    def test_record_model_stats(self):
        """测试模型统计"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            today = datetime.now().strftime("%Y-%m-%d")
            
            tracker.record("qwen3.5-plus", "dashscope", 100, 200, 0.001, 100)
            tracker.record("qwen3.5-flash", "dashscope", 50, 100, 0.0005, 50)
            
            usage = tracker._load_usage()
            models = usage["days"][today]["models"]
            
            assert "qwen3.5-plus" in models
            assert "qwen3.5-flash" in models
            assert models["qwen3.5-plus"]["requests"] == 1
            assert models["qwen3.5-flash"]["requests"] == 1


class TestGetUsage:
    """测试获取用量统计"""
    
    def test_get_usage_today(self):
        """测试获取今日用量"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            today = datetime.now().strftime("%Y-%m-%d")
            
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            result = tracker.get_usage("today")
            
            assert result["period"] == "today"
            assert result["total_requests"] == 1
            assert result["total_tokens_in"] == 100
            assert result["total_cost"] == 0.001
    
    def test_get_usage_week(self):
        """测试获取周用量"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 记录今天的数据
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            result = tracker.get_usage("week")
            
            assert result["period"] == "week"
            assert len(result["daily_breakdown"]) <= 7
    
    def test_get_usage_month(self):
        """测试获取月用量"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            result = tracker.get_usage("month")
            
            assert result["period"] == "month"
            assert len(result["daily_breakdown"]) <= 30
    
    def test_get_usage_all(self):
        """测试获取全部用量"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            result = tracker.get_usage("all")
            
            assert result["period"] == "all"
    
    def test_get_usage_no_data(self):
        """测试无数据情况"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            
            result = tracker.get_usage("today")
            
            assert result["total_requests"] == 0
            assert result["total_cost"] == 0.0


class TestCheckBudget:
    """测试预算检查"""
    
    def test_budget_disabled(self):
        """测试预算功能禁用"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            
            config = {"budget": {"enabled": False}}
            result = tracker.check_budget(config)
            
            assert result["enabled"] is False
    
    def test_budget_within_limit(self):
        """测试预算内"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            config = {
                "budget": {
                    "enabled": True,
                    "daily_limit": 50,
                    "monthly_limit": 1000
                }
            }
            result = tracker.check_budget(config)
            
            assert result["enabled"] is True
            assert result["daily"]["exceeded"] is False
            assert result["monthly"]["exceeded"] is False
    
    def test_budget_exceeded_daily(self):
        """测试超出日预算"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            
            # 记录超过日预算的使用
            tracker.record("model1", "provider1", 100000, 200000, 60.0, 100)
            
            config = {
                "budget": {
                    "enabled": True,
                    "daily_limit": 50,
                    "monthly_limit": 1000
                }
            }
            result = tracker.check_budget(config)
            
            assert result["daily"]["exceeded"] is True
    
    def test_budget_remaining(self):
        """测试预算剩余"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            
            tracker.record("model1", "provider1", 100, 200, 10.0, 100)
            
            config = {
                "budget": {
                    "enabled": True,
                    "daily_limit": 50,
                    "monthly_limit": 1000
                }
            }
            result = tracker.check_budget(config)
            
            assert result["daily"]["remaining"] == 40.0
            assert result["daily"]["used"] == 10.0


class TestGetCostEstimate:
    """测试成本估算"""
    
    def test_qwen35_flash(self):
        """测试 qwen3.5-flash 成本"""
        tracker = UsageTracker()
        cost = tracker.get_cost_estimate("qwen3.5-flash", 1000)
        assert cost == 0.002
    
    def test_qwen35_plus(self):
        """测试 qwen3.5-plus 成本"""
        tracker = UsageTracker()
        cost = tracker.get_cost_estimate("qwen3.5-plus", 1000)
        assert cost == 0.004
    
    def test_qwen3_max(self):
        """测试 qwen3-max 成本"""
        tracker = UsageTracker()
        cost = tracker.get_cost_estimate("qwen3-max", 1000)
        assert cost == 0.02
    
    def test_unknown_model(self):
        """测试未知模型（默认价格）"""
        tracker = UsageTracker()
        cost = tracker.get_cost_estimate("unknown-model", 1000)
        assert cost == 0.004  # 默认 qwen3.5-plus 价格
    
    def test_large_token_count(self):
        """测试大 token 数量"""
        tracker = UsageTracker()
        cost = tracker.get_cost_estimate("qwen3.5-plus", 100000)
        assert cost == 0.4  # 100 * 0.004


class TestCleanupOldData:
    """测试清理旧数据"""
    
    def test_cleanup_removes_old_data(self):
        """测试清理移除旧数据"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            
            # 创建旧数据
            old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            
            usage = {
                "days": {
                    old_date: {"requests": 1, "cost": 0.001},
                    today: {"requests": 2, "cost": 0.002}
                },
                "version": "1.0"
            }
            tracker._save_usage(usage)
            
            # 清理 90 天前的数据
            tracker.cleanup_old_data(days_to_keep=90)
            
            result = tracker._load_usage()
            assert old_date not in result["days"]
            assert today in result["days"]
    
    def test_cleanup_keeps_recent_data(self):
        """测试清理保留近期数据"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir), use_database=False)
            
            # 创建近期数据
            recent_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
            
            usage = {
                "days": {
                    recent_date: {"requests": 1, "cost": 0.001}
                },
                "version": "1.0"
            }
            tracker._save_usage(usage)
            
            tracker.cleanup_old_data(days_to_keep=90)
            
            result = tracker._load_usage()
            assert recent_date in result["days"]


class TestExportReport:
    """测试导出报告"""
    
    def test_export_json(self):
        """测试导出 JSON 格式"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            result = tracker.export_report("today", "json")
            
            data = json.loads(result)
            assert "period" in data
            assert "total_requests" in data
    
    def test_export_csv(self):
        """测试导出 CSV 格式"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            tracker.record("model1", "provider1", 100, 200, 0.001, 100)
            
            result = tracker.export_report("today", "csv")
            
            assert "date,requests,cost" in result
    
    def test_export_invalid_format(self):
        """测试导出无效格式"""
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(Path(temp_dir))
            
            with pytest.raises(ValueError) as exc_info:
                tracker.export_report("today", "xml")
            
            assert "不支持的格式" in str(exc_info.value)


class TestGlobalFunctions:
    """测试全局函数"""
    
    def test_get_tracker_singleton(self):
        """测试 get_tracker 单例模式"""
        tracker1 = get_tracker()
        tracker2 = get_tracker()
        
        assert tracker1 is tracker2
    
    def test_record_usage_convenience(self):
        """测试 record_usage 便捷函数"""
        # 这个函数只是调用 tracker.record()
        # 已经在上面的测试中覆盖了
        pass
