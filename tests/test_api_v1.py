#!/usr/bin/env python3
"""
测试 RESTful API v1 路由
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.v1 import router as api_v1_router

client = TestClient(app)


class TestAPIInfo:
    """测试 API 信息接口"""
    
    def test_get_api_info(self):
        """获取 API 信息"""
        response = client.get("/api/v1/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Bridge Server API"
        assert data["version"] == "1.6.0"
        assert "endpoints" in data


class TestAuthEndpoints:
    """测试认证相关接口"""
    
    def test_create_token_invalid_credentials(self):
        """测试创建 token - 无效凭证"""
        response = client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "wrong"}
        )
        assert response.status_code == 401
    
    def test_create_token_missing_fields(self):
        """测试创建 token - 缺少字段"""
        response = client.post(
            "/api/v1/auth/token",
            json={"username": "admin"}
        )
        assert response.status_code == 422


class TestRoutingEndpoints:
    """测试路由管理接口"""
    
    def test_get_routing_strategy(self):
        """获取路由策略"""
        response = client.get("/api/v1/routing/strategy")
        assert response.status_code == 200
        data = response.json()
        assert "strategy" in data
        assert "model_mapping" in data
    
    def test_get_routing_providers(self):
        """获取路由 Provider 列表"""
        response = client.get("/api/v1/routing/providers")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
    
    def test_test_routing(self):
        """测试路由决策"""
        response = client.post(
            "/api/v1/routing/test",
            json={"message": "用 Python 写个快速排序"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_type" in data
        assert "selected_model" in data
        assert data["task_type"] == "coding"


class TestUsageEndpoints:
    """测试用量统计接口"""
    
    def test_get_usage_summary(self):
        """获取用量统计摘要"""
        response = client.get("/api/v1/usage/summary?period=today")
        assert response.status_code == 200
        data = response.json()
        assert "period" in data
        assert "total_requests" in data
        assert "total_cost" in data
    
    def test_get_usage_summary_invalid_period(self):
        """获取用量统计 - 无效周期"""
        response = client.get("/api/v1/usage/summary?period=invalid")
        assert response.status_code == 422
    
    def test_get_usage_records(self):
        """获取用量记录"""
        response = client.get("/api/v1/usage/records?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
    
    def test_export_usage_json(self):
        """导出用量报告 - JSON"""
        response = client.get("/api/v1/usage/export?period=week&format=json")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"
        assert "content" in data
    
    def test_export_usage_csv(self):
        """导出用量报告 - CSV"""
        response = client.get("/api/v1/usage/export?period=week&format=csv")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "csv"


class TestProviderEndpoints:
    """测试 Provider 管理接口"""
    
    def test_list_providers(self):
        """列出所有 Provider"""
        response = client.get("/api/v1/providers/list")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
    
    def test_test_provider_not_found(self):
        """测试 Provider - 不存在"""
        response = client.post(
            "/api/v1/providers/nonexistent/test",
            json={"message": "test"}
        )
        assert response.status_code == 404


class TestHealthEndpoints:
    """测试健康检查接口"""
    
    def test_root(self):
        """根路径"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.6.0"
        assert data["status"] == "running"
    
    def test_health_check(self):
        """健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
    
    def test_readiness_check(self):
        """就绪检查"""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data


class TestLegacyEndpoints:
    """测试旧版本接口（兼容性）"""
    
    def test_get_models(self):
        """列出所有模型"""
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
    
    def test_get_routing_config(self):
        """获取路由配置"""
        response = client.get("/api/routing")
        assert response.status_code == 200
        data = response.json()
        assert "strategy" in data
    
    def test_get_usage(self):
        """获取用量统计"""
        response = client.get("/api/usage?period=today")
        assert response.status_code == 200
        data = response.json()
        assert "period" in data or "days" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
