#!/usr/bin/env python3
"""
数据库迁移脚本 - v1.6.0
从 SQLite 迁移到 MySQL/PostgreSQL
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_sqlite_data(usage_file: Path) -> list:
    """加载 SQLite/JSON 数据"""
    if not usage_file.exists():
        logger.warning(f"用量文件不存在：{usage_file}")
        return []
    
    with open(usage_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    records = []
    days = data.get('days', {})
    
    for date, day_data in days.items():
        models = day_data.get('models', {})
        
        for model, model_data in models.items():
            # 估算记录（因为旧数据没有详细记录）
            requests = model_data.get('requests', 0)
            if requests == 0:
                continue
            
            # 平均分配
            avg_tokens_in = model_data.get('tokens_in', 0) // max(requests, 1)
            avg_tokens_out = model_data.get('tokens_out', 0) // max(requests, 1)
            avg_cost = model_data.get('cost', 0) / max(requests, 1)
            
            for i in range(requests):
                records.append({
                    'date': date,
                    'model': model,
                    'provider': 'unknown',
                    'input_tokens': avg_tokens_in,
                    'output_tokens': avg_tokens_out,
                    'cost': avg_cost,
                    'duration_ms': 0,
                    'success': True
                })
    
    logger.info(f"加载 {len(records)} 条历史记录")
    return records


def migrate_to_mysql(database_url: str, usage_file: Path):
    """迁移到 MySQL"""
    logger.info(f"开始迁移到 MySQL | {database_url.split('://')[0]}")
    
    # 初始化数据库
    from services.database import init_database, UsageRecord
    from sqlalchemy import text
    
    db_manager = init_database(database_url)
    session = db_manager.get_session()
    
    try:
        # 加载旧数据
        records = load_sqlite_data(usage_file)
        
        if not records:
            logger.info("没有需要迁移的数据")
            return
        
        # 批量插入
        batch_size = 100
        total_inserted = 0
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            orm_records = []
            
            for record in batch:
                import uuid
                orm_record = UsageRecord(
                    user_id=1,
                    request_id=str(uuid.uuid4()),
                    provider=record['provider'],
                    model=record['model'],
                    input_tokens=record['input_tokens'],
                    output_tokens=record['output_tokens'],
                    cost=record['cost'],
                    duration_ms=record['duration_ms'],
                    success=1 if record['success'] else 0,
                    created_at=datetime.strptime(record['date'], '%Y-%m-%d')
                )
                orm_records.append(orm_record)
            
            session.bulk_save_objects(orm_records)
            session.commit()
            total_inserted += len(batch)
            logger.info(f"已迁移 {total_inserted}/{len(records)} 条记录")
        
        logger.info(f"迁移完成！共 {total_inserted} 条记录")
        
    except Exception as e:
        session.rollback()
        logger.error(f"迁移失败：{e}")
        raise
    finally:
        session.close()


def verify_migration(database_url: str, expected_count: int):
    """验证迁移结果"""
    from services.database import DatabaseManager, UsageRecord
    from sqlalchemy import func
    
    db_manager = DatabaseManager(database_url)
    session = db_manager.get_session()
    
    try:
        count = session.query(func.count(UsageRecord.id)).scalar()
        logger.info(f"数据库记录数：{count}")
        
        if count == expected_count:
            logger.info("✓ 迁移验证成功")
            return True
        else:
            logger.warning(f"⚠ 记录数不匹配：期望 {expected_count}, 实际 {count}")
            return False
            
    except Exception as e:
        logger.error(f"验证失败：{e}")
        return False
    finally:
        session.close()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据库迁移工具')
    parser.add_argument('--database-url', type=str, required=True,
                        help='目标数据库 URL')
    parser.add_argument('--usage-file', type=str,
                        default=str(Path.home() / '.bridge-server' / 'usage.json'),
                        help='源用量文件路径')
    parser.add_argument('--verify', action='store_true',
                        help='迁移后验证')
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Bridge Server 数据库迁移工具 v1.6.0")
    logger.info("=" * 60)
    
    # 执行迁移
    migrate_to_mysql(args.database_url, Path(args.usage_file))
    
    # 验证
    if args.verify:
        # 重新加载计算期望数量
        records = load_sqlite_data(Path(args.usage_file))
        verify_migration(args.database_url, len(records))
    
    logger.info("=" * 60)
    logger.info("迁移完成")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
