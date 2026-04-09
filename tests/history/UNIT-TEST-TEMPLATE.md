# 单元测试模板

**适用**: Layer 1 测试 - 函数/方法级别测试

---

## 测试文件结构

```python
"""
测试文件：tests/unit/test_<module>.py
命名规范：
  - 测试文件：test_<module>.py
  - 测试类：Test<ClassName>
  - 测试函数：test_<scenario>_<expected_result>
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

# 添加源代码路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestAuth:
    """认证模块测试"""
    
    # ===== 成功场景 (Happy Path) =====
    
    def test_verify_token_with_valid_bearer(self, mock_env):
        """测试有效的 Bearer Token"""
        from app.auth import verify_token
        
        result = verify_token(authorization="Bearer valid-token-123")
        assert result is True
    
    def test_verify_token_with_direct_token(self, mock_env):
        """测试直接 Token（无 Bearer 前缀）"""
        from app.auth import verify_token
        
        result = verify_token(authorization="valid-token-123")
        assert result is True
    
    # ===== 失败场景 (Error Path) =====
    
    def test_verify_token_missing_authorization(self):
        """测试缺少认证信息"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization=None)
        
        assert exc_info.value.status_code == 401
        assert "缺少认证信息" in exc_info.value.detail
    
    def test_verify_token_invalid_token(self, mock_env):
        """测试无效 Token"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="Bearer invalid-token")
        
        assert exc_info.value.status_code == 401
        assert "无效的 Token" in exc_info.value.detail
    
    # ===== 边界情况 (Edge Cases) =====
    
    def test_verify_token_empty_string(self, mock_env):
        """测试空字符串 Token"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="Bearer ")
        
        assert exc_info.value.status_code == 401
    
    def test_verify_token_malformed_bearer(self):
        """测试格式错误的 Bearer"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="BearerToken invalid")
        
        assert exc_info.value.status_code == 401
    
    def test_verify_token_whitespace_only(self, mock_env):
        """测试纯空白字符 Token"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="Bearer    ")
        
        assert exc_info.value.status_code == 401
    
    # ===== 安全场景 (Security Cases) =====
    
    def test_verify_token_timing_attack_protection(self, mock_env):
        """测试定时攻击防护"""
        from app.auth import verify_token
        import time
        
        # 测量有效 Token 的时间
        start = time.time()
        for _ in range(100):
            verify_token(authorization="Bearer valid-token-123")
        valid_time = time.time() - start
        
        # 测量无效 Token 的时间
        start = time.time()
        for _ in range(100):
            try:
                verify_token(authorization="Bearer invalid-token")
            except:
                pass
        invalid_time = time.time() - start
        
        # 时间差异应该小于 10%（防止定时攻击）
        time_diff = abs(valid_time - invalid_time) / max(valid_time, invalid_time)
        assert time_diff < 0.1, "Token 验证存在定时攻击风险"
    
    # ===== 配置场景 (Configuration Cases) =====
    
    def test_verify_token_no_configured_tokens(self, temp_config_dir):
        """测试未配置 auth_tokens 的情况"""
        from app.auth import verify_token, load_config
        from fastapi import HTTPException
        
        # 创建没有 auth_tokens 的配置
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text("""
server:
  host: 0.0.0.0
  port: 8080
""")
        
        with patch('pathlib.Path.home', return_value=temp_config_dir):
            with pytest.raises(HTTPException) as exc_info:
                verify_token(authorization="Bearer any-token")
            
            assert exc_info.value.status_code == 503
            assert "未配置认证" in exc_info.value.detail


class TestRouter:
    """路由模块测试"""
    
    def test_route_model_select_provider(self, mock_env):
        """测试模型路由选择提供商"""
        from app.router import route_model
        
        result = route_model("qwen3.5-plus")
        assert result["provider"] == "dashscope"
        assert result["enabled"] is True
    
    def test_route_model_invalid_model(self, mock_env):
        """测试无效模型"""
        from app.router import route_model
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            route_model("non-existent-model")
        
        assert exc_info.value.status_code == 400
        assert "不支持的模型" in exc_info.value.detail
    
    def test_route_model_disabled_provider(self, mock_env):
        """测试禁用的提供商"""
        from app.router import route_model
        from fastapi import HTTPException
        
        # Mock 禁用的提供商
        with patch('app.router.load_config') as mock:
            mock.return_value = {
                'providers': {
                    'dashscope': {'enabled': False}
                }
            }
            
            with pytest.raises(HTTPException) as exc_info:
                route_model("qwen3.5-plus")
            
            assert exc_info.value.status_code == 503
            assert "服务不可用" in exc_info.value.detail


class TestConfig:
    """配置解析测试"""
    
    def test_load_config_success(self, temp_config_dir):
        """测试成功加载配置"""
        from providers.loader import load_config
        
        # 创建测试配置
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text("""
server:
  host: 0.0.0.0
  port: 8080
  auth_tokens:
    - "test-token"
""")
        
        with patch('pathlib.Path.home', return_value=temp_config_dir):
            config = load_config()
            
            assert config["server"]["host"] == "0.0.0.0"
            assert config["server"]["port"] == 8080
            assert "test-token" in config["server"]["auth_tokens"]
    
    def test_load_config_missing_file(self):
        """测试配置文件不存在"""
        from providers.loader import load_config
        from fastapi import HTTPException
        
        with patch('pathlib.Path.home', return_value=Path("/nonexistent")):
            with pytest.raises(HTTPException) as exc_info:
                load_config()
            
            assert exc_info.value.status_code == 503
            assert "配置文件不存在" in exc_info.value.detail
    
    def test_load_config_invalid_yaml(self, temp_config_dir):
        """测试无效的 YAML 格式"""
        from providers.loader import load_config
        
        # 创建无效的 YAML
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text("""
server:
  host: 0.0.0.0
    port: 8080  # 错误的缩进
""")
        
        with patch('pathlib.Path.home', return_value=temp_config_dir):
            with pytest.raises(Exception):  # YAML 解析错误
                load_config()
```

---

## 测试夹具（Fixtures）

```python
# tests/conftest.py
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def temp_config_dir():
    """创建临时配置目录"""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def mock_env():
    """Mock 环境变量"""
    test_tokens = ["valid-token-123", "admin-token-456"]
    test_api_keys = {
        "DASHSCOPE_API_KEY": "sk-dashscope-test",
        "MOONSHOT_API_KEY": "sk-moonshot-test"
    }
    
    with patch.dict('os.environ', {
        **test_api_keys,
        'BRIDGE_SERVER_TESTING': 'true'
    }):
        with patch('app.auth.load_config') as mock_config:
            mock_config.return_value = {
                'server': {
                    'auth_tokens': test_tokens
                },
                'providers': {
                    'dashscope': {
                        'enabled': True,
                        'api_key_env': 'DASHSCOPE_API_KEY',
                        'models': {
                            'qwen3.5-plus': {'cost': 0.004}
                        }
                    }
                }
            }
            yield


@pytest.fixture
def sample_request():
    """示例请求"""
    return {
        "model": "qwen3.5-plus",
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "max_tokens": 100
    }


@pytest.fixture
def sample_response():
    """示例响应"""
    return {
        "choices": [
            {
                "message": {
                    "content": "你好！有什么可以帮助你的？",
                    "role": "assistant"
                },
                "finish_reason": "stop",
                "index": 0
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30
        }
    }


@pytest.fixture
def mock_budget():
    """Mock 预算配置"""
    return {
        'enabled': True,
        'daily_limit': 50,
        'monthly_limit': 1000,
        'over_budget_action': 'downgrade'
    }
```

---

## 运行测试

```bash
# 运行单个测试文件
pytest tests/unit/test_auth.py -v

# 运行特定测试类
pytest tests/unit/test_auth.py::TestAuth -v

# 运行特定测试
pytest tests/unit/test_auth.py::TestAuth::test_verify_token_with_valid_bearer -v

# 运行所有单元测试
pytest tests/unit/ -v

# 生成覆盖率报告
pytest tests/unit/ --cov=app --cov-report=html
```

---

## 测试检查清单

### 测试设计

- [ ] 包含成功场景（Happy Path）
- [ ] 包含失败场景（Error Path）
- [ ] 包含边界情况（Edge Cases）
- [ ] 包含安全场景（Security Cases）
- [ ] 包含配置场景（Configuration Cases）

### 断言质量

- [ ] 断言具体错误消息
- [ ] 断言状态码
- [ ] 断言返回数据结构
- [ ] 断言副作用（如数据库变更）
- [ ] 避免断言实现细节

### 测试独立性

- [ ] 测试之间无依赖
- [ ] 使用临时目录/数据库
- [ ] Mock 外部服务
- [ ] 清理测试资源
- [ ] 可重复运行

### 测试可维护性

- [ ] 测试函数名称清晰
- [ ] 使用 Arrange-Act-Assert 模式
- [ ] 避免魔法数字
- [ ] 使用有意义的变量名
- [ ] 添加必要的注释

---

*最后更新：2026-04-05*
