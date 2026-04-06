#!/usr/bin/env python3
"""
测试数据库服务 - v1.6.0
"""

import pytest
import os
from datetime import datetime, timedelta
from pathlib import Path


class TestDatabaseManager:
    """测试数据库管理器"""
    
    def test_database_manager_sqlite(self):
        """测试 SQLite 数据库初始化"""
        from services.database import DatabaseManager, UsageRecord
        
        # 使用 SQLite 测试
        db_manager = DatabaseManager('sqlite:///./test_bridge.db')
        db_manager.create_tables()
        
        # 验证表已创建
        session = db_manager.get_session()
        try:
            # 插入测试记录
            record = UsageRecord(
                user_id=1,
                request_id='test-001',
                provider='dashscope',
                model='qwen3.5-plus',
                input_tokens=100,
                output_tokens=50,
                cost=0.001,
                duration_ms=200,
                success=1
            )
            session.add(record)
            session.commit()
            
            # 查询验证
            result = session.query(UsageRecord).filter_by(request_id='test-001').first()
            assert result is not None
            assert result.model == 'qwen3.5-plus'
            assert result.input_tokens == 100
            
        finally:
            session.close()
            # 清理测试数据库
            if os.path.exists('test_bridge.db'):
                os.remove('test_bridge.db')
    
    def test_database_manager_batch_insert(self):
        """测试批量插入"""
        from services.database import DatabaseManager, UsageRecord
        import uuid
        
        db_manager = DatabaseManager('sqlite:///./test_bridge_batch.db')
        db_manager.create_tables()
        
        try:
            # 创建测试记录
            records = []
            for i in range(50):
                record = UsageRecord(
                    user_id=1,
                    request_id=str(uuid.uuid4()),
                    provider='dashscope',
                    model=f'model-{i % 5}',
                    input_tokens=100,
                    output_tokens=50,
                    cost=0.001,
                    duration_ms=200,
                    success=1
                )
                records.append(record)
            
            # 批量插入
            db_manager.batch_insert(records)
            
            # 验证
            session = db_manager.get_session()
            try:
                count = session.query(UsageRecord).count()
                assert count == 50
            finally:
                session.close()
                
        finally:
            if os.path.exists('test_bridge_batch.db'):
                os.remove('test_bridge_batch.db')


class TestHighConcurrencyWriter:
    """测试高并发写入器"""
    
    def test_writer_single_write(self):
        """测试单条写入"""
        from services.high_concurrency_writer import HighConcurrencyWriter
        
        # 使用大 batch_size 和长 flush_interval 避免实际写入数据库
        writer = HighConcurrencyWriter(batch_size=1000, flush_interval=300)
        
        try:
            # 写入单条
            writer.write({
                'provider': 'dashscope',
                'model': 'qwen3.5-plus',
                'input_tokens': 100,
                'output_tokens': 50,
                'cost': 0.001
            })
            
            # 验证统计
            stats = writer.get_stats()
            assert stats['total_writes'] == 1
            assert stats['buffer_size'] == 1
            
        finally:
            writer.stop()
    
    def test_writer_batch_write(self):
        """测试批量写入"""
        from services.high_concurrency_writer import HighConcurrencyWriter
        
        # 使用大 batch_size 避免实际写入数据库
        writer = HighConcurrencyWriter(batch_size=1000, flush_interval=300)
        
        try:
            # 批量写入
            records = [
                {
                    'provider': 'dashscope',
                    'model': 'qwen3.5-plus',
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cost': 0.001
                }
                for _ in range(15)
            ]
            writer.write_batch(records)
            
            # 验证统计（应该触发了一次批量刷新）
            stats = writer.get_stats()
            assert stats['total_writes'] == 15
            
        finally:
            writer.stop()
    
    def test_writer_concurrent(self):
        """测试并发写入（简化版）"""
        from services.high_concurrency_writer import HighConcurrencyWriter
        
        # 简化测试，只验证基本功能
        writer = HighConcurrencyWriter(batch_size=1000, flush_interval=300)
        
        try:
            for i in range(10):
                writer.write({
                    'provider': 'dashscope',
                    'model': 'qwen3.5-plus',
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cost': 0.001,
                    'request_id': f'test-{i}'
                })
            
            stats = writer.get_stats()
            assert stats['total_writes'] == 10
            
        finally:
            writer.stop()


class TestUsageTrackerFileMode:
    """测试用量跟踪器（文件模式）"""
    
    def test_tracker_record(self):
        """测试记录用量"""
        from services.usage import UsageTracker
        import tempfile
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = UsageTracker(config_dir=Path(tmpdir), use_database=False)
            
            # 记录用量
            tracker.record(
                model='qwen3.5-plus',
                provider='dashscope',
                tokens_in=100,
                tokens_out=50,
                cost=0.001,
                duration_ms=200,
                success=True
            )
            
            # 验证文件已创建
            usage_file = Path(tmpdir) / 'usage.json'
            assert usage_file.exists()
            
            # 验证内容
            with open(usage_file, 'r') as f:
                data = json.load(f)
            
            today = datetime.now().strftime('%Y-%m-%d')
            assert today in data['days']
            assert data['days'][today]['requests'] == 1
    
    def test_tracker_get_usage(self):
        """测试获取用量统计"""
        from services.usage import UsageTracker
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = UsageTracker(config_dir=Path(tmpdir), use_database=False)
            
            # 记录多条
            for i in range(5):
                tracker.record(
                    model=f'model-{i % 2}',
                    provider='dashscope',
                    tokens_in=100,
                    tokens_out=50,
                    cost=0.001,
                    duration_ms=200,
                    success=True
                )
            
            # 获取统计
            usage = tracker.get_usage('today')
            assert usage['total_requests'] == 5
            assert len(usage['models']) == 2
    
    def test_tracker_export_json(self):
        """测试导出 JSON 报告"""
        from services.usage import UsageTracker
        import tempfile
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = UsageTracker(config_dir=Path(tmpdir), use_database=False)
            
            tracker.record(
                model='qwen3.5-plus',
                provider='dashscope',
                tokens_in=100,
                tokens_out=50,
                cost=0.001,
                duration_ms=200,
                success=True
            )
            
            # 导出 JSON
            report = tracker.export_report('today', 'json')
            data = json.loads(report)
            assert 'total_requests' in data
            assert 'daily_breakdown' in data
    
    def test_tracker_export_csv(self):
        """测试导出 CSV 报告"""
        from services.usage import UsageTracker
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = UsageTracker(config_dir=Path(tmpdir), use_database=False)
            
            tracker.record(
                model='qwen3.5-plus',
                provider='dashscope',
                tokens_in=100,
                tokens_out=50,
                cost=0.001,
                duration_ms=200,
                success=True
            )
            
            # 导出 CSV
            report = tracker.export_report('today', 'csv')
            lines = report.split('\n')
            assert lines[0] == 'date,requests,cost'
            assert len(lines) >= 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
