"""Pytest 配置文件"""
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_config_dir():
    """创建临时配置目录"""
    temp_dir = tempfile.mkdtemp(prefix="bridge-server-test-")
    yield Path(temp_dir)
    # 清理
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_config(temp_config_dir):
    """模拟配置文件"""
    # 创建.bridge-server 子目录
    bridge_dir = temp_config_dir / ".bridge-server"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = bridge_dir / "config.yaml"
    config_file.write_text("""
server:
  host: 0.0.0.0
  port: 8080
  auth_tokens:
    - test-token-123
    - another-token-456

providers:
  dashscope:
    enabled: true
    api_key: test-api-key
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    models:
      qwen3.5-flash:
        cost: 0.002
        use_case: 简单任务
      qwen3.5-plus:
        cost: 0.004
        use_case: 通用任务
      qwen3-max:
        cost: 0.02
        use_case: 复杂任务

routing:
  strategy: balanced
  model_mapping: {}

budget:
  enabled: true
  daily_limit: 50
  monthly_limit: 1000
""")
    return config_file


@pytest.fixture
def mock_env(mock_config):
    """模拟环境变量和配置路径"""
    with patch('pathlib.Path.home', return_value=mock_config.parent.parent):
        yield


@pytest.fixture
def client(mock_env):
    """创建 FastAPI 测试客户端"""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
