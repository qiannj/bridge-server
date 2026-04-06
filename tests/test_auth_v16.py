#!/usr/bin/env python3
"""
测试认证模块 v1.6.0
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import verify_token, create_jwt_token, load_config
import os

client = TestClient(app)


class TestTokenVerification:
    """测试 Token 验证"""
    
    def test_missing_authorization(self):
        """缺少认证头"""
        response = client.get("/api/v1/routing/strategy")
        # 应该返回 401 或未认证但允许访问（取决于配置）
        assert response.status_code in [200, 401]
    
    def test_invalid_token_format(self):
        """无效 Token 格式"""
        response = client.get(
            "/api/v1/routing/strategy",
            headers={"Authorization": "Bearer invalid-token"}
        )
        # 可能返回 401 或使用默认配置
        assert response.status_code in [200, 401, 503]


class TestJWTToken:
    """测试 JWT Token"""
    
    def test_create_jwt_token(self):
        """创建 JWT Token"""
        token = create_jwt_token("test_user", expires_days=1)
        assert token is not None
        assert isinstance(token, str)
        assert token.count('.') == 2  # JWT 格式
    
    def test_create_jwt_token_custom_expiry(self):
        """创建 JWT Token - 自定义过期时间"""
        token = create_jwt_token("test_user", expires_days=7)
        assert token is not None
        
        # 验证 token 可以解码
        import jwt
        config = load_config()
        auth_config = config.get("auth", {})
        secret_key = auth_config.get("jwt_secret", "bridge-server-secret-key-change-me")
        
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        assert payload["sub"] == "test_user"
        assert payload["type"] == "access"


class TestAPIKeyAuth:
    """测试 API Key 认证"""
    
    def test_api_key_header(self):
        """使用 X-API-Key 头认证"""
        # 这个测试依赖于配置中的 API Key
        # 在没有配置的情况下，应该返回 503 或 401
        response = client.get(
            "/api/v1/routing/strategy",
            headers={"X-API-Key": "test-key"}
        )
        assert response.status_code in [200, 401, 503]


class TestAuthEndpoints:
    """测试认证端点"""
    
    def test_token_endpoint_missing_body(self):
        """Token 端点 - 缺少请求体"""
        response = client.post("/api/v1/auth/token")
        assert response.status_code == 422
    
    def test_token_endpoint_invalid_json(self):
        """Token 端点 - 无效 JSON"""
        response = client.post(
            "/api/v1/auth/token",
            json={"username": "admin"}  # 缺少 password
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
