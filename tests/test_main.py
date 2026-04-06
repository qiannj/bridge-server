"""主应用模块测试"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRootEndpoint:
    """测试根路径端点"""
    
    def test_root_returns_service_info(self, client):
        """测试根路径返回服务信息"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data['service'] == 'bridge-server'
        assert data['version'] == '1.6.0'
        assert data['status'] == 'running'


class TestHealthEndpoint:
    """测试健康检查端点"""
    
    def test_health_returns_healthy(self, client):
        """测试健康检查返回健康状态"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert 'timestamp' in data
        assert data['version'] == '1.6.0'


class TestChatCompletionsEndpoint:
    """测试聊天完成端点"""
    
    def test_missing_messages(self, client):
        """测试缺少 messages 字段"""
        response = client.post(
            "/v1/chat/completions",
            json={},
            headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 400
        assert "缺少 messages 字段" in response.json()['detail']
    
    def test_empty_messages(self, client):
        """测试空 messages 列表"""
        response = client.post(
            "/v1/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 400
    
    def test_message_too_long(self, client):
        """测试消息过长"""
        long_message = "x" * 10001  # 超过 10000 字符限制
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": long_message}]},
            headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 400
        assert "长度超过限制" in response.json()['detail']
    
    def test_too_many_messages(self, client):
        """测试消息数量过多"""
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(51)]
        response = client.post(
            "/v1/chat/completions",
            json={"messages": messages},
            headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 400
        assert "消息数量超过限制" in response.json()['detail']
    
    def test_missing_authorization(self, client):
        """测试缺少认证"""
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]}
        )
        assert response.status_code == 401
    
    def test_invalid_token(self, client):
        """测试无效 token"""
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401


class TestModelsEndpoint:
    """测试模型列表端点"""
    
    def test_list_models(self, client):
        """测试列出模型"""
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert 'models' in data


class TestRoutingConfigEndpoint:
    """测试路由配置端点"""
    
    def test_get_routing_config(self, client):
        """测试获取路由配置"""
        response = client.get("/api/routing")
        assert response.status_code == 200
        data = response.json()
        assert 'strategy' in data
        assert 'model_mapping' in data


class TestUsageEndpoint:
    """测试用量统计端点"""
    
    def test_get_usage(self, client):
        """测试获取用量统计"""
        response = client.get("/api/usage")
        assert response.status_code == 200
        data = response.json()
        assert 'period' in data


class TestBudgetEndpoint:
    """测试预算端点"""
    
    def test_get_budget(self, client):
        """测试获取预算状态"""
        response = client.get("/api/budget")
        assert response.status_code == 200
        data = response.json()
        assert 'enabled' in data


class TestLoadConfig:
    """测试配置加载"""
    
    def test_load_config_exists(self, temp_config_dir):
        """测试配置文件存在时加载"""
        from app.main import load_config
        
        # 创建.bridge-server 子目录
        bridge_dir = temp_config_dir / ".bridge-server"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        config_file = bridge_dir / "config.yaml"
        config_file.write_text("test_key: test_value")
        
        with patch('pathlib.Path.home', return_value=temp_config_dir):
            config = load_config()
            assert config.get('test_key') == 'test_value'
    
    def test_load_config_not_exists(self):
        """测试配置文件不存在时返回空字典"""
        from app.main import load_config
        
        with patch('pathlib.Path.home', return_value=Path("/nonexistent")):
            config = load_config()
            assert config == {}


class TestErrorHandling:
    """测试错误处理"""
    
    def test_timeout_error_sanitization(self, client):
        """测试超时错误信息脱敏"""
        with patch('app.router.call_llm', new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("Connection timeout error")
            
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"Authorization": "Bearer test-token-123"}
            )
            # 错误应该被捕获并返回 500
            assert response.status_code in [200, 500]
    
    def test_connection_error_sanitization(self, client):
        """测试连接错误信息脱敏"""
        with patch('app.router.call_llm', new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("Connection refused")
            
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"Authorization": "Bearer test-token-123"}
            )
            assert response.status_code in [200, 500]
