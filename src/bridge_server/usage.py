#!/usr/bin/env python3
"""
异步用量跟踪模块 - v2.0
优化用量统计和预算控制性能
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import aiofiles

from .utils.connection_pools import get_connection_pool_manager, get_db_connection

logger = logging.getLogger(__name__)


class UsageTrackerAsync:
    """异步用量跟踪器"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".bridge-server"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.usage_file = self.config_dir / "usage.json"
        self.budget_file = self.config_dir / "budget.json"
        self.db_file = self.config_dir / "usage.db"
        
        # 内存缓存（减少磁盘I/O）
        self._usage_cache = {}
        self._budget_cache = {}
        self._cache_ttl = 60  # 1分钟缓存
        
        # 批量写入队列（提高性能）
        self._write_queue = asyncio.Queue()
        self._batch_size = 100
        self._batch_timeout = 5.0  # 5秒
        self._writer_task = None
    
    async def initialize(self) -> None:
        """初始化用量跟踪器"""
        # 初始化数据库
        await self._init_database()
        
        # 启动批量写入任务
        self._writer_task = asyncio.create_task(self._batch_writer())
        
        # 加载预算配置
        await self._load_budget_config()
        
        logger.info("✅ 异步用量跟踪器初始化完成")
    
    async def _init_database(self) -> None:
        """初始化SQLite数据库"""
        try:
            await get_connection_pool_manager()
            
            async with await get_db_connection() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS usage_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        date TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        model TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        task_type TEXT,
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost_usd REAL DEFAULT 0.0,
                        cost_rmb REAL DEFAULT 0.0,
                        duration_ms REAL DEFAULT 0.0,
                        success BOOLEAN DEFAULT TRUE,
                        created_at REAL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON usage_records(date)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_date ON usage_records(user_id, date)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_model ON usage_records(model)")
                await conn.commit()
            
        except Exception as e:
            logger.error(f"数据库初始化失败: {str(e)}")
            raise
    
    async def _load_budget_config(self) -> None:
        """加载预算配置"""
        try:
            if self.budget_file.exists():
                async with aiofiles.open(self.budget_file, 'r', encoding='utf-8') as f:
                    self._budget_cache = json.loads(await f.read())
            else:
                # 默认预算配置
                self._budget_cache = {
                    "daily_limit_rmb": 100.0,
                    "monthly_limit_rmb": 2000.0,
                    "alerts": {
                        "daily_threshold": 0.8,
                        "monthly_threshold": 0.9
                    },
                    "created_at": time.time()
                }
                await self._save_budget_config()
        
        except Exception as e:
            logger.warning(f"预算配置加载失败: {str(e)}")
            self._budget_cache = {}
    
    async def _save_budget_config(self) -> None:
        """保存预算配置"""
        try:
            async with aiofiles.open(self.budget_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self._budget_cache, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.error(f"预算配置保存失败: {str(e)}")
    
    async def _batch_writer(self) -> None:
        """批量写入任务"""
        batch = []
        last_write = time.time()
        
        try:
            while True:
                try:
                    # 等待新数据或超时
                    timeout = max(0.1, self._batch_timeout - (time.time() - last_write))
                    record = await asyncio.wait_for(self._write_queue.get(), timeout=timeout)
                    batch.append(record)
                    
                    # 检查是否需要批量写入
                    should_write = (
                        len(batch) >= self._batch_size or
                        time.time() - last_write >= self._batch_timeout
                    )
                    
                    if should_write and batch:
                        await self._flush_batch(batch)
                        batch.clear()
                        last_write = time.time()
                
                except asyncio.TimeoutError:
                    # 超时也要写入
                    if batch:
                        await self._flush_batch(batch)
                        batch.clear()
                        last_write = time.time()
                
        except asyncio.CancelledError:
            # 关闭时写入剩余数据
            if batch:
                await self._flush_batch(batch)
            raise
        
        except Exception as e:
            logger.error(f"批量写入任务异常: {str(e)}")
    
    async def _flush_batch(self, batch: List[Dict[str, Any]]) -> None:
        """批量写入数据库"""
        if not batch:
            return
        
        try:
            # 批量插入
            insert_sql = """
                INSERT INTO usage_records (
                    timestamp, date, user_id, model, provider, task_type,
                    input_tokens, output_tokens, total_tokens, 
                    cost_usd, cost_rmb, duration_ms, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            records = []
            for record in batch:
                records.append((
                    record.get("timestamp", time.time()),
                    record.get("date", datetime.now().strftime("%Y-%m-%d")),
                    record.get("user_id", "unknown"),
                    record.get("model", ""),
                    record.get("provider", ""),
                    record.get("task_type", "general"),
                    record.get("input_tokens", 0),
                    record.get("output_tokens", 0),
                    record.get("total_tokens", 0),
                    record.get("cost_usd", 0.0),
                    record.get("cost_rmb", 0.0),
                    record.get("duration_ms", 0.0),
                    record.get("success", True)
                ))
            
            async with await get_db_connection() as conn:
                await conn.executemany(insert_sql, records)
                await conn.commit()
            
            logger.debug(f"批量写入完成: {len(records)} 条记录")
        
        except Exception as e:
            logger.error(f"批量写入失败: {str(e)}")
    
    async def record_usage(
        self,
        model: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        user_id: str = "unknown",
        task_type: str = "general",
        duration_ms: float = 0.0,
        success: bool = True
    ) -> None:
        """记录用量（异步，加入写入队列）"""
        
        total_tokens = input_tokens + output_tokens
        cost_rmb = cost_usd * 7.2  # USD to RMB汇率
        
        record = {
            "timestamp": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "user_id": user_id,
            "model": model,
            "provider": provider,
            "task_type": task_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "cost_rmb": cost_rmb,
            "duration_ms": duration_ms,
            "success": success
        }
        
        # 加入写入队列
        try:
            self._write_queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning("用量记录队列已满，丢弃记录")
    
    async def get_usage_stats(
        self, 
        period: str = "today",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取用量统计"""
        try:
            # 计算时间范围
            now = datetime.now()
            if period == "today":
                start_date = now.strftime("%Y-%m-%d")
                end_date = start_date
            elif period == "week":
                start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
                end_date = now.strftime("%Y-%m-%d")
            elif period == "month":
                start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
                end_date = now.strftime("%Y-%m-%d")
            else:
                start_date = now.strftime("%Y-%m-%d")
                end_date = start_date
            
            # 构建查询
            sql = """
                SELECT 
                    COUNT(*) as total_requests,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(total_tokens) as total_tokens,
                    SUM(cost_rmb) as total_cost_rmb,
                    AVG(duration_ms) as avg_duration_ms,
                    COUNT(CASE WHEN success THEN 1 END) as successful_requests
                FROM usage_records 
                WHERE date >= ? AND date <= ?
            """
            params = [start_date, end_date]
            
            if user_id:
                sql += " AND user_id = ?"
                params.append(user_id)
            
            async with await get_db_connection() as conn:
                async with conn.execute(sql, params) as cursor:
                    row = await cursor.fetchone()
                    
                    if row:
                        return {
                            "period": period,
                            "start_date": start_date,
                            "end_date": end_date,
                            "user_id": user_id,
                            "total_requests": row[0] or 0,
                            "total_input_tokens": row[1] or 0,
                            "total_output_tokens": row[2] or 0,
                            "total_tokens": row[3] or 0,
                            "total_cost_rmb": round(row[4] or 0, 2),
                            "avg_duration_ms": round(row[5] or 0, 2),
                            "successful_requests": row[6] or 0,
                            "success_rate": round((row[6] or 0) / max(row[0] or 1, 1), 3)
                        }
        
        except Exception as e:
            logger.error(f"用量统计查询失败: {str(e)}")
        
        return {}
    
    async def get_budget_status(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """获取预算状态"""
        
        # 今日用量
        today_stats = await self.get_usage_stats("today", user_id)
        today_cost = today_stats.get("total_cost_rmb", 0)
        
        # 本月用量
        month_stats = await self.get_usage_stats("month", user_id)
        month_cost = month_stats.get("total_cost_rmb", 0)
        
        # 预算限制
        daily_limit = self._budget_cache.get("daily_limit_rmb", 100.0)
        monthly_limit = self._budget_cache.get("monthly_limit_rmb", 2000.0)
        
        # 计算使用率
        daily_usage_rate = today_cost / daily_limit if daily_limit > 0 else 0
        monthly_usage_rate = month_cost / monthly_limit if monthly_limit > 0 else 0
        
        # 告警阈值
        alerts = self._budget_cache.get("alerts", {})
        daily_threshold = alerts.get("daily_threshold", 0.8)
        monthly_threshold = alerts.get("monthly_threshold", 0.9)
        
        return {
            "user_id": user_id,
            "today": {
                "used_rmb": today_cost,
                "limit_rmb": daily_limit,
                "usage_rate": round(daily_usage_rate, 3),
                "alert": daily_usage_rate >= daily_threshold,
                "exceeded": daily_usage_rate >= 1.0
            },
            "month": {
                "used_rmb": month_cost,
                "limit_rmb": monthly_limit,
                "usage_rate": round(monthly_usage_rate, 3),
                "alert": monthly_usage_rate >= monthly_threshold,
                "exceeded": monthly_usage_rate >= 1.0
            },
            "timestamp": time.time()
        }
    
    async def close(self) -> None:
        """关闭用量跟踪器"""
        # 取消批量写入任务
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        
        logger.info("异步用量跟踪器已关闭")


# 全局实例
usage_tracker: Optional[UsageTrackerAsync] = None


async def get_usage_tracker() -> UsageTrackerAsync:
    """获取用量跟踪器实例"""
    global usage_tracker
    if usage_tracker is None:
        usage_tracker = UsageTrackerAsync()
        await usage_tracker.initialize()
    return usage_tracker


async def record_usage_async(
    model: str,
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    user_id: str = "unknown",
    task_type: str = "general",
    duration_ms: float = 0.0,
    cost_usd: float = 0.0
) -> None:
    """便捷的异步用量记录函数"""
    tracker = await get_usage_tracker()
    await tracker.record_usage(
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        user_id=user_id,
        task_type=task_type,
        duration_ms=duration_ms,
        success=True
    )
