# Bridge Server TODO

当前仓库已经收敛到单一运行时主线，剩余工作主要集中在工程化补强。

## 高优先级

1. **补齐真实 Provider 集成验证**
   - 为有凭证的环境增加 smoke test
   - 覆盖流式输出、预算统计、路由退化

2. **发布与部署规范化**
   - 统一 Docker 镜像产物
   - 梳理版本号与发布流程

3. **增强 CI 深度**
   - 在现有 GitHub Actions 基础上增加 runtime smoke test
   - 逐步覆盖 `/health`、`/ready`、`/api/routing`、Prometheus 导出

## 中优先级

1. **强化配置校验**
   - 在启动时校验 routing / providers / budget 配置结构
   - 给出更明确的错误信息

2. **整理 CLI**
   - 继续清理平台相关逻辑
   - 统一默认入口和探活逻辑

3. **补齐运维文档**
   - 增加日志字段说明
   - 增加 Prometheus / Grafana 示例面板

## 低优先级

1. **预算告警通知**
2. **更细粒度的多租户能力**
3. **更多 Provider 适配**
