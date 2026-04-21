#!/usr/bin/env python3
"""
Providers Package - Bridge Server v2.0
统一AI平台接口和Provider管理
"""

from .base import BaseProvider, ModelInfo, ProviderFactory, ProviderStatus, ProviderMetrics
from .manager import ProviderManager, RoutingStrategy, ProviderConfig
from .oauth_manager import OAuthTokenManager

# 导入具体Provider实现
from .dashscope import DashScopeProvider
from .openai import OpenAIProvider  
from .moonshot import MoonshotProvider

__all__ = [
    # 基础类
    "BaseProvider",
    "ModelInfo", 
    "ProviderFactory",
    "ProviderStatus",
    "ProviderMetrics",
    
    # 管理器
    "ProviderManager",
    "RoutingStrategy", 
    "ProviderConfig",

    # OAuth
    "OAuthTokenManager",
    
    # 具体实现
    "DashScopeProvider",
    "OpenAIProvider",
    "MoonshotProvider",
]

# 版本信息
__version__ = "2.0.0"