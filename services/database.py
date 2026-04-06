#!/usr/bin/env python3
"""
数据库模型 - v1.6.0
支持 MySQL/PostgreSQL 高并发存储
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Index, BigInteger, DECIMAL, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)

Base = declarative_base()


class UsageRecord(Base):
    """用量记录表"""
    __tablename__ = 'usage_records'
    
    # 使用 Integer 兼容 SQLite，MySQL/PostgreSQL 会自动处理大整数
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    request_id = Column(String(64), unique=True, nullable=False, index=True)
    provider = Column(String(32), nullable=False)
    model = Column(String(64), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    cost = Column(Float, nullable=False)
    duration_ms = Column(Integer, nullable=False, default=0)
    success = Column(Integer, nullable=False, default=1)  # 1=success, 0=failed
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_user_time', 'user_id', 'created_at'),
        Index('idx_model_time', 'model', 'created_at'),
        Index('idx_provider_time', 'provider', 'created_at'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'request_id': self.request_id,
            'provider': self.provider,
            'model': self.model,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'cost': float(self.cost),
            'duration_ms': self.duration_ms,
            'success': bool(self.success),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __init__(self, **kwargs):
        # SQLite 不需要显式设置 id，让它自动增长
        if 'id' in kwargs and kwargs['id'] is None:
            del kwargs['id']
        super().__init__(**kwargs)


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, database_url: str = None):
        """
        初始化数据库连接
        
        Args:
            database_url: 数据库连接 URL
                - MySQL: mysql+mysqlconnector://user:pass@host:3306/bridge_server
                - PostgreSQL: postgresql://user:pass@host:5432/bridge_server
                - SQLite: sqlite:///./bridge_server.db (仅用于测试)
        """
        if database_url is None:
            # 从环境变量读取
            database_url = os.getenv(
                'DATABASE_URL',
                'sqlite:///./bridge_server.db'
            )
        
        self.database_url = database_url
        self.engine = None
        self.SessionLocal = None
        self._init_engine()
    
    def _init_engine(self):
        """初始化数据库引擎"""
        try:
            if self.database_url.startswith('mysql'):
                # MySQL 配置优化
                self.engine = create_engine(
                    self.database_url,
                    pool_size=20,  # 连接池大小
                    max_overflow=40,  # 最大溢出连接数
                    pool_recycle=3600,  # 1 小时回收连接
                    pool_pre_ping=True,  # 连接前 ping 测试
                    echo=False  # 关闭 SQL 日志
                )
            elif self.database_url.startswith('postgresql'):
                # PostgreSQL 配置优化
                self.engine = create_engine(
                    self.database_url,
                    pool_size=20,
                    max_overflow=40,
                    pool_recycle=3600,
                    pool_pre_ping=True,
                    echo=False
                )
            else:
                # SQLite (仅测试用)
                self.engine = create_engine(
                    self.database_url,
                    connect_args={'check_same_thread': False}
                )
            
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            logger.info(f"数据库连接初始化成功 | {self.database_url.split('://')[0]}")
            
        except Exception as e:
            logger.error(f"数据库连接失败：{e}")
            raise
    
    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(bind=self.engine)
        logger.info("数据库表创建完成")
    
    def drop_tables(self):
        """删除所有表（谨慎使用）"""
        Base.metadata.drop_all(bind=self.engine)
        logger.info("数据库表已删除")
    
    def get_session(self):
        """获取数据库会话"""
        if self.SessionLocal is None:
            raise RuntimeError("数据库未初始化")
        return self.SessionLocal()
    
    def batch_insert(self, records: list):
        """
        批量插入记录（高并发优化）
        
        Args:
            records: UsageRecord 对象列表
        """
        session = self.get_session()
        try:
            # 对于 SQLite，使用普通 add 而不是 bulk_save_objects
            if self.database_url.startswith('sqlite'):
                for record in records:
                    # 确保 id 为 None 让 SQLite 自动增长
                    record.id = None
                    session.add(record)
                session.commit()
            else:
                session.bulk_save_objects(records)
                session.commit()
            logger.info(f"批量插入 {len(records)} 条记录成功")
        except Exception as e:
            session.rollback()
            logger.error(f"批量插入失败：{e}")
            raise
        finally:
            session.close()
    
    def execute_query(self, query_func):
        """
        执行查询（带错误处理）
        
        Args:
            query_func: 接收 session 的函数
        
        Returns:
            查询结果
        """
        session = self.get_session()
        try:
            result = query_func(session)
            return result
        except Exception as e:
            logger.error(f"查询失败：{e}")
            raise
        finally:
            session.close()


# 全局数据库实例
_db_manager: DatabaseManager = None


def get_db_manager() -> DatabaseManager:
    """获取全局数据库管理器"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def init_database(database_url: str = None):
    """初始化数据库"""
    global _db_manager
    _db_manager = DatabaseManager(database_url)
    _db_manager.create_tables()
    return _db_manager
