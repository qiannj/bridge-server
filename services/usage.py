#!/usr/bin/env python3
"""
用量统计服务 - v1.6.0 升级
支持 SQLite（向后兼容）和 MySQL/PostgreSQL（高并发）
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
import os

logger = logging.getLogger(__name__)


class UsageTracker:
    """用量跟踪器 - 支持双后端"""
    
    def __init__(self, config_dir: Optional[Path] = None, use_database: bool = True):
        self.config_dir = config_dir or Path.home() / ".bridge-server"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.usage_file = self.config_dir / "usage.json"
        self.budget_file = self.config_dir / "budget.json"
        
        # 数据库支持
        self.use_database = use_database
        self._db_manager = None
        self._init_database()
    
    def _init_database(self):
        """初始化数据库连接"""
        if not self.use_database:
            return
        
        try:
            from services.database import get_db_manager, UsageRecord
            self._db_manager = get_db_manager()
            logger.info("数据库后端已启用")
        except Exception as e:
            logger.warning(f"数据库初始化失败，降级到文件后端：{e}")
            self.use_database = False
    
    def record(
        self,
        model: str,
        provider: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        duration_ms: int,
        success: bool = True,
        user_id: int = 1,
        request_id: str = None
    ):
        """
        记录一次 API 调用
        
        Args:
            model: 模型名称
            provider: 提供商
            tokens_in: 输入 token 数
            tokens_out: 输出 token 数
            cost: 费用（元）
            duration_ms: 耗时（毫秒）
            success: 是否成功
            user_id: 用户 ID
            request_id: 请求唯一 ID
        """
        import uuid
        
        if request_id is None:
            request_id = str(uuid.uuid4())
        
        # 优先使用高并发写入器
        if self.use_database:
            try:
                from services.high_concurrency_writer import record_usage_async
                record_usage_async(
                    model=model,
                    provider=provider,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost=cost,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    success=success
                )
                logger.debug(f"记录用量（数据库）| model={model} | cost=¥{cost:.4f}")
                return
            except Exception as e:
                logger.warning(f"数据库写入失败，降级到文件：{e}")
                self.use_database = False
        
        # 降级到文件存储（向后兼容）
        usage = self._load_usage()
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today not in usage["days"]:
            usage["days"][today] = {
                "requests": 0,
                "requests_success": 0,
                "requests_failed": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost": 0.0,
                "models": {},
            }
        
        usage["days"][today]["requests"] += 1
        if success:
            usage["days"][today]["requests_success"] += 1
        else:
            usage["days"][today]["requests_failed"] += 1
        
        usage["days"][today]["tokens_in"] += tokens_in
        usage["days"][today]["tokens_out"] += tokens_out
        usage["days"][today]["cost"] += cost
        
        if model not in usage["days"][today]["models"]:
            usage["days"][today]["models"][model] = {
                "requests": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost": 0.0,
            }
        
        usage["days"][today]["models"][model]["requests"] += 1
        usage["days"][today]["models"][model]["tokens_in"] += tokens_in
        usage["days"][today]["models"][model]["tokens_out"] += tokens_out
        usage["days"][today]["models"][model]["cost"] += cost
        
        self._save_usage(usage)
        logger.info(f"记录用量 | model={model} | cost=¥{cost:.4f} | tokens={tokens_in + tokens_out}")
    
    def get_usage(self, period: str = "today") -> Dict:
        """
        获取用量统计
        
        Args:
            period: today, week, month, all
        
        Returns:
            用量数据字典
        """
        # 优先从数据库查询
        if self.use_database and self._db_manager:
            try:
                return self._get_usage_from_db(period)
            except Exception as e:
                logger.warning(f"数据库查询失败，降级到文件：{e}")
                self.use_database = False
        
        # 从文件读取
        return self._get_usage_from_file(period)
    
    def _get_usage_from_db(self, period: str) -> Dict:
        """从数据库获取用量统计"""
        from sqlalchemy import func, and_
        from services.database import UsageRecord
        
        session = self._db_manager.get_session()
        
        try:
            # 计算日期范围
            now = datetime.utcnow()
            if period == "today":
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == "yesterday":
                start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date + timedelta(days=1)
            elif period == "week":
                start_date = now - timedelta(days=7)
            elif period == "month":
                start_date = now - timedelta(days=30)
            else:
                start_date = datetime(2000, 1, 1)
            
            # 基础查询
            query = session.query(UsageRecord).filter(
                UsageRecord.created_at >= start_date
            )
            
            if period == "yesterday":
                query = query.filter(UsageRecord.created_at < end_date)
            
            records = query.all()
            
            # 汇总统计
            result = {
                "period": period,
                "total_requests": len(records),
                "total_requests_success": sum(1 for r in records if r.success),
                "total_requests_failed": sum(1 for r in records if not r.success),
                "total_tokens_in": sum(r.input_tokens for r in records),
                "total_tokens_out": sum(r.output_tokens for r in records),
                "total_cost": float(sum(r.cost for r in records)),
                "models": {},
                "providers": {},
                "daily_breakdown": []
            }
            
            # 按模型汇总
            for record in records:
                if record.model not in result["models"]:
                    result["models"][record.model] = {"requests": 0, "cost": 0.0}
                result["models"][record.model]["requests"] += 1
                result["models"][record.model]["cost"] += float(record.cost)
                
                # 按提供商汇总
                if record.provider not in result["providers"]:
                    result["providers"][record.provider] = {"requests": 0, "cost": 0.0}
                result["providers"][record.provider]["requests"] += 1
                result["providers"][record.provider]["cost"] += float(record.cost)
            
            # 每日明细
            daily_stats = session.query(
                func.date(UsageRecord.created_at).label('date'),
                func.count(UsageRecord.id).label('requests'),
                func.sum(UsageRecord.cost).label('cost')
            ).filter(
                UsageRecord.created_at >= start_date
            ).group_by(
                func.date(UsageRecord.created_at)
            ).order_by(
                func.date(UsageRecord.created_at).desc()
            ).all()
            
            result["daily_breakdown"] = [
                {"date": str(row.date), "requests": row.requests, "cost": float(row.cost)}
                for row in daily_stats
            ]
            
            return result
            
        finally:
            session.close()
    
    def _get_usage_from_file(self, period: str) -> Dict:
        """从文件获取用量统计（向后兼容）"""
        usage = self._load_usage()
        days = usage.get("days", {})
        
        if period == "today":
            target_dates = [datetime.now().strftime("%Y-%m-%d")]
        elif period == "yesterday":
            target_dates = [(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")]
        elif period == "week":
            target_dates = [
                (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(7)
            ]
        elif period == "month":
            target_dates = [
                (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(30)
            ]
        else:
            target_dates = list(days.keys())
        
        result = {
            "period": period,
            "total_requests": 0,
            "total_requests_success": 0,
            "total_requests_failed": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost": 0.0,
            "models": {},
            "providers": {},
            "daily_breakdown": [],
        }
        
        for date in sorted(target_dates, reverse=True):
            if date not in days:
                continue
            
            day_data = days[date]
            result["total_requests"] += day_data.get("requests", 0)
            result["total_requests_success"] += day_data.get("requests_success", 0)
            result["total_requests_failed"] += day_data.get("requests_failed", 0)
            result["total_tokens_in"] += day_data.get("tokens_in", 0)
            result["total_tokens_out"] += day_data.get("tokens_out", 0)
            result["total_cost"] += day_data.get("cost", 0.0)
            
            for model, model_data in day_data.get("models", {}).items():
                if model not in result["models"]:
                    result["models"][model] = {"requests": 0, "cost": 0.0}
                result["models"][model]["requests"] += model_data.get("requests", 0)
                result["models"][model]["cost"] += model_data.get("cost", 0.0)
            
            for provider in ["dashscope", "moonshot", "openai", "minimax"]:
                if provider in day_data:
                    if provider not in result["providers"]:
                        result["providers"][provider] = {"requests": 0, "cost": 0.0}
                    result["providers"][provider]["requests"] += day_data[provider].get("requests", 0)
                    result["providers"][provider]["cost"] += day_data[provider].get("cost", 0.0)
            
            result["daily_breakdown"].append({
                "date": date,
                "requests": day_data.get("requests", 0),
                "cost": day_data.get("cost", 0.0),
            })
        
        return result
    
    def check_budget(self, config: Dict) -> Dict:
        """检查预算状态"""
        budget_config = config.get("budget", {})
        
        if not budget_config.get("enabled", False):
            return {"enabled": False}
        
        daily_limit = budget_config.get("daily_limit", 50)
        monthly_limit = budget_config.get("monthly_limit", 1000)
        
        today_usage = self.get_usage("today")
        month_usage = self.get_usage("month")
        
        daily_remaining = daily_limit - today_usage["total_cost"]
        monthly_remaining = monthly_limit - month_usage["total_cost"]
        
        daily_exceeded = daily_remaining < 0
        monthly_exceeded = monthly_remaining < 0
        
        return {
            "enabled": True,
            "daily": {
                "limit": daily_limit,
                "used": today_usage["total_cost"],
                "remaining": daily_remaining,
                "exceeded": daily_exceeded,
            },
            "monthly": {
                "limit": monthly_limit,
                "used": month_usage["total_cost"],
                "remaining": monthly_remaining,
                "exceeded": monthly_exceeded,
            },
            "action": budget_config.get("over_budget_action", "alert"),
        }
    
    def get_cost_estimate(self, model: str, tokens: int) -> float:
        """估算成本"""
        price_table = {
            "qwen3.5-flash": 0.002,
            "qwen3.5-plus": 0.004,
            "qwen3-max": 0.02,
            "qwen3-coder-plus": 0.008,
            "kimi-chat": 0.012,
            "kimi-k2.5": 0.025,
            "gpt-3.5-turbo": 0.014,
            "gpt-4-turbo": 0.07,
            "gpt-4o": 0.105,
            "MiniMax-M2.5": 0.005,
        }
        
        price_per_1k = price_table.get(model, 0.004)
        return (tokens / 1000) * price_per_1k
    
    def _load_usage(self) -> Dict:
        """加载用量数据"""
        if not self.usage_file.exists():
            return {"days": {}, "version": "1.0"}
        
        try:
            with open(self.usage_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载用量数据失败：{e}")
            return {"days": {}, "version": "1.0"}
    
    def _save_usage(self, usage: Dict):
        """保存用量数据"""
        with open(self.usage_file, "w", encoding="utf-8") as f:
            json.dump(usage, f, indent=2, ensure_ascii=False)
    
    def cleanup_old_data(self, days_to_keep: int = 90):
        """清理旧数据"""
        if self.use_database:
            logger.info("数据库模式自动管理数据保留，跳过清理")
            return
        
        usage = self._load_usage()
        cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
        
        original_count = len(usage["days"])
        usage["days"] = {k: v for k, v in usage["days"].items() if k >= cutoff_date}
        removed_count = original_count - len(usage["days"])
        
        if removed_count > 0:
            self._save_usage(usage)
            logger.info(f"清理 {removed_count} 天的旧用量数据")
    
    def export_report(self, period: str = "month", format: str = "json") -> str:
        """导出用量报告"""
        usage = self.get_usage(period)
        
        if format == "json":
            return json.dumps(usage, indent=2, ensure_ascii=False)
        elif format == "csv":
            lines = ["date,requests,cost"]
            for day in usage["daily_breakdown"]:
                lines.append(f"{day['date']},{day['requests']},{day['cost']:.2f}")
            return "\n".join(lines)
        else:
            raise ValueError(f"不支持的格式：{format}")


# 全局用量跟踪器实例
_tracker: Optional[UsageTracker] = None


def get_tracker() -> UsageTracker:
    """获取全局用量跟踪器"""
    global _tracker
    if _tracker is None:
        # 自动检测是否使用数据库
        use_db = os.getenv('DATABASE_URL') is not None
        _tracker = UsageTracker(use_database=use_db)
    return _tracker


def record_usage(
    model: str,
    provider: str,
    tokens_in: int,
    tokens_out: int,
    cost: float,
    duration_ms: int,
    success: bool = True,
):
    """快捷记录用量"""
    get_tracker().record(
        model, provider, tokens_in, tokens_out, cost, duration_ms, success
    )
