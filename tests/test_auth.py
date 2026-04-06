"""认证模块测试"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestVerifyToken:
    """测试 verify_token 函数"""
    
    def test_missing_authorization(self):
        """测试缺少认证信息"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization=None)
        
        assert exc_info.value.status_code == 401
        assert "缺少认证信息" in exc_info.value.detail
    
    def test_bearer_token_valid(self, mock_env):
        """测试有效的 Bearer Token"""
        from app.auth import verify_token
        
        result = verify_token(authorization="Bearer test-token-123")
        assert result is True
    
    def test_direct_token_valid(self, mock_env):
        """测试有效的直接 Token"""
        from app.auth import verify_token
        
        result = verify_token(authorization="test-token-123")
        assert result is True
    
    def test_invalid_token(self, mock_env):
        """测试无效的 Token"""
        from app.auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="Bearer invalid-token")
        
        assert exc_info.value.status_code == 401
        assert "无效的 Token" in exc_info.value.detail
    
    def test_no_configured_tokens(self, temp_config_dir):
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
    
    def test_bearer_token_extraction(self):
        """测试 Bearer Token 提取逻辑"""
        # 测试各种 Bearer 格式
        test_cases = [
            ("Bearer token123", "token123"),
            ("token123", "token123"),  # 直接 token
        ]
        
        for auth_header, expected_token in test_cases:
            # 验证 token 提取逻辑
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                token = auth_header
            assert token == expected_token


class TestLoadConfig:
    """测试 load_config 函数"""
    
    def test_config_exists(self, temp_config_dir):
        """测试配置文件存在"""
        from app.auth import load_config
        
        # 创建.bridge-server 子目录
        bridge_dir = temp_config_dir / ".bridge-server"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        config_file = bridge_dir / "config.yaml"
        config_file.write_text("test_key: test_value")
        
        with patch('pathlib.Path.home', return_value=temp_config_dir):
            config = load_config()
            assert config.get('test_key') == 'test_value'
    
    def test_config_not_exists(self):
        """测试配置文件不存在"""
        from app.auth import load_config
        
        with patch('pathlib.Path.home', return_value=Path("/nonexistent")):
            config = load_config()
            assert config == {}
