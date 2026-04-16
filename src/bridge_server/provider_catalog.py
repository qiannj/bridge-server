"""
Bridge Server Provider Loader

加载和管理全球 LLM 提供商注册表
支持 15 家主流提供商，40+ 模型
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ModelPricing:
    """模型定价信息"""

    currency: str
    input_per_1k: float
    output_per_1k: float

    def __str__(self) -> str:
        return f"{self.input_per_1k}/{self.output_per_1k} {self.currency}/1K tokens"


@dataclass
class Model:
    """模型信息"""

    id: str
    name: str
    description: str
    context_length: int
    max_output_tokens: int
    description_en: str = ""
    pricing: Optional[ModelPricing] = None
    capabilities: List[str] = field(default_factory=list)
    benchmarks: Dict[str, float] = field(default_factory=dict)
    release_date: str = ""
    provider: str = ""  # 提供商 ID

    def supports(self, capability: str) -> bool:
        """检查是否支持某项能力"""
        return capability in self.capabilities

    def get_benchmark(self, name: str) -> Optional[float]:
        """获取基准测试分数"""
        return self.benchmarks.get(name)


@dataclass
class Provider:
    """提供商信息"""

    id: str
    name: str
    name_en: str
    region: str
    headquarters: str
    website: str
    base_url: str
    api_key_env: str
    api_key_url: str
    status: str
    languages: List[str] = field(default_factory=list)
    models: List[Model] = field(default_factory=list)

    @property
    def api_base(self) -> str:
        """Backward-compatible alias for existing wizard code."""
        return self.base_url

    def get_model(self, model_id: str) -> Optional[Model]:
        """根据 ID 获取模型"""
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def get_cheapest_model(self) -> Optional[Model]:
        """获取最便宜的模型"""
        if not self.models:
            return None

        valid_models = [m for m in self.models if m.pricing]
        if not valid_models:
            return None

        return min(valid_models, key=lambda m: m.pricing.input_per_1k)

    def get_most_powerful_model(self) -> Optional[Model]:
        """获取最强模型（通常是最贵的）"""
        if not self.models:
            return None

        valid_models = [m for m in self.models if m.pricing]
        if not valid_models:
            return None

        return max(valid_models, key=lambda m: m.pricing.input_per_1k)


class ProviderLoader:
    """提供商加载器"""

    def __init__(self, registry_path: Optional[str] = None):
        """
        初始化加载器

        Args:
            registry_path: registry.yaml 路径，默认使用内置路径
        """
        if registry_path is None:
            # 默认路径
            self.registry_path = Path(__file__).parent / "registry.yaml"
        else:
            self.registry_path = Path(registry_path)

        self.providers: Dict[str, Provider] = {}
        self.last_loaded: Optional[datetime] = None
        self._cache: Dict[str, Any] = {}

    def load(self, force: bool = False) -> Dict[str, Provider]:
        """
        加载提供商注册表

        Args:
            force: 是否强制重新加载（忽略缓存）

        Returns:
            提供商字典 {id: Provider}
        """
        # 检查缓存
        if not force and self.providers and self.last_loaded:
            logger.debug("使用缓存的提供商注册表")
            return self.providers

        # 检查文件是否存在
        if not self.registry_path.exists():
            logger.error(f"注册表文件不存在：{self.registry_path}")
            raise FileNotFoundError(
                f"Provider registry not found: {self.registry_path}"
            )

        logger.info(f"加载提供商注册表：{self.registry_path}")

        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            # 解析提供商列表
            providers_data = data.get("providers", [])

            for provider_data in providers_data:
                provider = self._parse_provider(provider_data)
                if provider:
                    self.providers[provider.id] = provider

            self.last_loaded = datetime.now()
            logger.info(f"成功加载 {len(self.providers)} 家提供商")

            return self.providers

        except yaml.YAMLError as e:
            logger.error(f"YAML 解析错误：{e}")
            raise
        except Exception as e:
            logger.error(f"加载注册表失败：{e}")
            raise

    def _parse_provider(self, data: Dict[str, Any]) -> Optional[Provider]:
        """解析单个提供商数据"""
        try:
            # 解析模型列表
            models = []
            provider_id = data.get("id", "")
            for model_data in data.get("models", []):
                model = self._parse_model(model_data, provider_id)
                if model:
                    models.append(model)

            provider = Provider(
                id=data.get("id", ""),
                name=data.get("name", ""),
                name_en=data.get("name_en", ""),
                region=data.get("region", ""),
                headquarters=data.get("headquarters", ""),
                website=data.get("website", ""),
                base_url=data.get("base_url", ""),
                api_key_env=data.get("api_key_env", ""),
                api_key_url=data.get("api_key_url", ""),
                status=data.get("status", "unknown"),
                languages=data.get("languages", []),
                models=models,
            )

            return provider

        except Exception as e:
            logger.warning(f"解析提供商 {data.get('id', 'unknown')} 失败：{e}")
            return None

    def _parse_model(
        self, data: Dict[str, Any], provider_id: str = ""
    ) -> Optional[Model]:
        """解析单个模型数据"""
        try:
            # 解析定价信息
            pricing = None
            pricing_data = data.get("pricing")
            if pricing_data:
                pricing = ModelPricing(
                    currency=pricing_data.get("currency", "USD"),
                    input_per_1k=pricing_data.get("input_per_1k", 0),
                    output_per_1k=pricing_data.get("output_per_1k", 0),
                )

            model = Model(
                id=data.get("id", ""),
                name=data.get("name", ""),
                description=data.get("description", ""),
                description_en=data.get("description_en", ""),
                context_length=data.get("context_length", 0),
                max_output_tokens=data.get("max_output_tokens", 0),
                pricing=pricing,
                capabilities=data.get("capabilities", []),
                benchmarks=data.get("benchmarks", {}),
                release_date=data.get("release_date", ""),
                provider=provider_id,  # 设置提供商 ID
            )

            return model

        except Exception as e:
            logger.warning(f"解析模型 {data.get('id', 'unknown')} 失败：{e}")
            return None

    def get_provider(self, provider_id: str) -> Optional[Provider]:
        """获取指定提供商"""
        if not self.providers:
            self.load()
        return self.providers.get(provider_id)

    def get_model(self, provider_id: str, model_id: str) -> Optional[Model]:
        """获取指定模型"""
        provider = self.get_provider(provider_id)
        if provider:
            return provider.get_model(model_id)
        return None

    def list_providers(self, region: Optional[str] = None) -> List[Provider]:
        """
        列出所有提供商

        Args:
            region: 按区域过滤（CN/US/EU/SG）

        Returns:
            提供商列表
        """
        if not self.providers:
            self.load()

        if region:
            return [p for p in self.providers.values() if p.region == region]

        return list(self.providers.values())

    def search_models(
        self,
        capability: Optional[str] = None,
        min_context: Optional[int] = None,
        max_price: Optional[float] = None,
        currency: str = "CNY",
    ) -> List[Model]:
        """
        搜索模型

        Args:
            capability: 能力过滤（chat/code/vision/reasoning）
            min_context: 最小上下文长度
            max_price: 最高价格（每 1K tokens）
            currency: 货币类型

        Returns:
            模型列表
        """
        if not self.providers:
            self.load()

        results = []

        for provider in self.providers.values():
            for model in provider.models:
                # 能力过滤
                if capability and not model.supports(capability):
                    continue

                # 上下文长度过滤
                if min_context and model.context_length < min_context:
                    continue

                # 价格过滤
                if max_price and model.pricing:
                    if model.pricing.currency != currency:
                        # 简单汇率转换（实际应该用实时汇率）
                        if currency == "CNY" and model.pricing.currency == "USD":
                            price = model.pricing.input_per_1k * 7
                        elif currency == "USD" and model.pricing.currency == "CNY":
                            price = model.pricing.input_per_1k / 7
                        else:
                            price = model.pricing.input_per_1k
                    else:
                        price = model.pricing.input_per_1k

                    if price > max_price:
                        continue

                results.append(model)

        # 按价格排序
        results.sort(key=lambda m: m.pricing.input_per_1k if m.pricing else 999)

        return results

    def get_recommendation(
        self,
        use_case: str,
        region: Optional[str] = None,
        budget: Optional[float] = None,
    ) -> Optional[Model]:
        """
        根据使用场景推荐模型

        Args:
            use_case: 使用场景（chat/code/translation/reasoning）
            region: 首选区域
            budget: 预算限制（每 1K tokens）

        Returns:
            推荐的模型
        """
        # 搜索符合条件的模型
        models = self.search_models(capability=use_case, max_price=budget)

        if region:
            # 优先推荐指定区域的模型
            region_models = [
                m
                for m in models
                if any(
                    p.region == region and m in p.models
                    for p in self.providers.values()
                )
            ]
            if region_models:
                models = region_models

        if not models:
            return None

        # 返回性价比最高的（有基准测试分数优先）
        scored_models = []
        for model in models:
            score = 0
            if model.benchmarks.get("MMLU"):
                score += model.benchmarks["MMLU"]
            if model.context_length > 100000:
                score += 10
            scored_models.append((score, model))

        scored_models.sort(key=lambda x: x[0], reverse=True)
        return scored_models[0][1]

    def clear_cache(self):
        """清除缓存"""
        self.providers.clear()
        self._cache.clear()
        self.last_loaded = None

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        if not self.providers:
            self.load()

        total_models = sum(len(p.models) for p in self.providers.values())
        regions = {}
        for p in self.providers.values():
            regions[p.region] = regions.get(p.region, 0) + 1

        return {
            "total_providers": len(self.providers),
            "total_models": total_models,
            "regions": regions,
            "last_loaded": self.last_loaded.isoformat() if self.last_loaded else None,
        }


# 全局单例
_default_loader: Optional[ProviderLoader] = None


def get_loader(registry_path: Optional[str] = None) -> ProviderLoader:
    """获取全局加载器实例"""
    global _default_loader
    if _default_loader is None:
        _default_loader = ProviderLoader(registry_path)
    return _default_loader


def load_providers(force: bool = False) -> Dict[str, Provider]:
    """加载提供商注册表"""
    return get_loader().load(force)


def get_provider(provider_id: str) -> Optional[Provider]:
    """获取指定提供商"""
    return get_loader().get_provider(provider_id)


def get_model(provider_id: str, model_id: str) -> Optional[Model]:
    """获取指定模型"""
    return get_loader().get_model(provider_id, model_id)


def search_models(**kwargs) -> List[Model]:
    """搜索模型"""
    return get_loader().search_models(**kwargs)


def get_recommendation(use_case: str, **kwargs) -> Optional[Model]:
    """获取模型推荐"""
    return get_loader().get_recommendation(use_case, **kwargs)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    loader = ProviderLoader()
    providers = loader.load()

    print(f"\n✅ 成功加载 {len(providers)} 家提供商\n")

    # 显示所有提供商
    for provider_id, provider in providers.items():
        print(f"🏢 {provider.name} ({provider.name_en})")
        print(f"   区域：{provider.region}")
        print(f"   模型数：{len(provider.models)}")
        if provider.models:
            cheapest = provider.get_cheapest_model()
            if cheapest:
                print(f"   最便宜：{cheapest.name} - {cheapest.pricing}")
        print()

    # 统计信息
    stats = loader.get_stats()
    print(f"📊 统计信息:")
    print(f"   总提供商数：{stats['total_providers']}")
    print(f"   总模型数：{stats['total_models']}")
    print(f"   区域分布：{stats['regions']}")
