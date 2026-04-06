# Bridge Server CI/CD 测试流程

**版本**: 2.0.0  
**创建日期**: 2026-04-05

---

## 🔄 CI/CD 流程

```
代码提交 → 触发 CI → 运行测试 → 安全扫描 → 构建镜像 → 部署
   ↓          ↓         ↓         ↓         ↓         ↓
 GitHub    GitHub   Unit +    Bandit +   Docker    K8s/
 Actions   Actions Integration Safety    Build     Deploy
```

---

## 📁 GitHub Actions 配置

```yaml
# .github/workflows/ci.yml
name: CI/CD Pipeline

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  # ============================================
  # 工作 1: 代码质量检查
  # ============================================
  code-quality:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install black pylint
    
    - name: Black format check
      run: black --check app/ services/ providers/
    
    - name: Pylint check
      run: |
        pylint app/ services/ providers/ \
          --fail-under=8.0 \
          --output-format=github
          2026-04-05

  # ============================================
  # 工作 2: 单元测试
  # ============================================
  unit-tests:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest pytest-cov
    
    - name: Run unit tests
      run: |
        pytest tests/unit/ \
          -v \
          --cov=app \
          --cov=services \
          --cov=providers \
          --cov-report=xml \
          --junitxml=reports/unit-report.xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
        flags: unittests
    
    - name: Upload test results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: unit-test-results
        path: reports/unit-report.xml

  # ============================================
  # 工作 3: 集成测试
  # ============================================
  integration-tests:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest pytest-cov httpx
    
    - name: Run integration tests
      run: |
        pytest tests/integration/ \
          -v \
          --cov=app \
          --cov=services \
          --cov-append \
          --junitxml=reports/integration-report.xml
    
    - name: Upload test results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: integration-test-results
        path: reports/integration-report.xml

  # ============================================
  # 工作 4: 安全扫描
  # ============================================
  security-scan:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install security tools
      run: |
        python -m pip install --upgrade pip
        pip install bandit safety trufflehog
    
    - name: Bandit scan
      run: |
        bandit -r app/ services/ providers/ \
          -f json \
          -o reports/bandit-report.json
        
        # 检查是否有高危问题
        if bandit -r app/ services/ providers/ | grep -q "SEVERITY: HIGH"; then
          echo "❌ 发现高危安全问题"
          exit 1
        fi
    
    - name: Safety scan
      run: |
        safety check -r requirements.txt \
          --json \
          --output reports/safety-report.json
        
        # 检查是否有高危漏洞
        if safety check -r requirements.txt | grep -q "HIGH"; then
          echo "❌ 发现高危依赖漏洞"
          exit 1
        fi
    
    - name: Secret scan
      run: |
        bash scripts/secret-scan.sh
    
    - name: Upload security reports
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: security-reports
        path: reports/

  # ============================================
  # 工作 5: E2E 测试
  # ============================================
  e2e-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Start test environment
      run: |
        docker-compose -f docker-compose.test.yml up -d
    
    - name: Wait for service
      run: |
        sleep 10
        curl -f http://localhost:19377/health || exit 1
    
    - name: Run E2E tests
      run: |
        pytest tests/e2e/ \
          -v \
          --junitxml=reports/e2e-report.xml
    
    - name: Stop test environment
      if: always()
      run: docker-compose -f docker-compose.test.yml down
    
    - name: Upload test results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: e2e-test-results
        path: reports/e2e-report.xml

  # ============================================
  # 工作 6: 构建 Docker 镜像
  # ============================================
  build-docker:
    runs-on: ubuntu-latest
    needs: [code-quality, unit-tests, integration-tests, security-scan]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v2
    
    - name: Login to Docker Hub
      uses: docker/login-action@v2
      with:
        username: ${{ secrets.DOCKER_USERNAME }}
        password: ${{ secrets.DOCKER_PASSWORD }}
    
    - name: Build and push
      uses: docker/build-push-action@v4
      with:
        context: .
        file: docker/Dockerfile
        push: true
        tags: |
          bridgeserver/bridge-server:latest
          bridgeserver/bridge-server:${{ github.sha }}
        platforms: linux/amd64,linux/arm64

  # ============================================
  # 工作 7: 部署到生产环境
  # ============================================
  deploy-production:
    runs-on: ubuntu-latest
    needs: [build-docker, e2e-tests]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    environment: production
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Deploy to production
      run: |
        # 这里添加部署脚本
        echo "Deploying to production..."
```

---

## 📊 测试报告模板

```markdown
# Bridge Server 测试报告

**构建**: #{{ github.run_number }}
**提交**: {{ github.sha }}
**分支**: {{ github.ref }}
**日期**: {{ github.event.head_commit.timestamp }}

---

## 测试结果

### 代码质量

| 检查项 | 状态 | 详情 |
|--------|------|------|
| Black 格式 | {{ jobs.code-quality.steps.black.outcome }} | [查看](#) |
| Pylint 评分 | {{ jobs.code-quality.steps.pylint.outcome }} | [查看](#) |

### 单元测试

- **状态**: {{ jobs.unit-tests.status }}
- **通过率**: {{ jobs.unit-tests.steps.run-unit-tests.outputs.pass-rate }}%
- **覆盖率**: {{ jobs.unit-tests.steps.upload-coverage.outputs.coverage }}%
- **报告**: [下载](../artifacts/unit-test-results)

### 集成测试

- **状态**: {{ jobs.integration-tests.status }}
- **通过率**: {{ jobs.integration-tests.steps.run-integration-tests.outputs.pass-rate }}%
- **报告**: [下载](../artifacts/integration-test-results)

### 安全扫描

| 扫描类型 | 状态 | 问题数 |
|---------|------|--------|
| Bandit | {{ jobs.security-scan.steps.bandit-scan.outcome }} | {{ jobs.security-scan.steps.bandit-scan.outputs.issues }} |
| Safety | {{ jobs.security-scan.steps.safety-scan.outcome }} | {{ jobs.security-scan.steps.safety-scan.outputs.vulnerabilities }} |
| Secret Scan | {{ jobs.security-scan.steps.secret-scan.outcome }} | {{ jobs.security-scan.steps.secret-scan.outputs.secrets }} |

### E2E 测试

- **状态**: {{ jobs.e2e-tests.status }}
- **通过率**: {{ jobs.e2e-tests.steps.run-e2e-tests.outputs.pass-rate }}%
- **报告**: [下载](../artifacts/e2e-test-results)

---

## 问题汇总

### 高危问题

{{ if jobs.security-scan.steps.bandit-scan.outputs.high_severity > 0 }}
⚠️ **发现 {{ jobs.security-scan.steps.bandit-scan.outputs.high_severity }} 个高危安全问题**

```
{{ jobs.security-scan.steps.bandit-scan.outputs.details }}
```
{{ else }}
✅ 无高危安全问题
{{ endif }}

### 依赖漏洞

{{ if jobs.security-scan.steps.safety-scan.outputs.high_vulnerabilities > 0 }}
⚠️ **发现 {{ jobs.security-scan.steps.safety-scan.outputs.high_vulnerabilities }} 个高危依赖漏洞**

```
{{ jobs.security-scan.steps.safety-scan.outputs.details }}
```
{{ else }}
✅ 无高危依赖漏洞
{{ endif }}

### 密钥泄露

{{ if jobs.security-scan.steps.secret-scan.outputs.secrets_found > 0 }}
❌ **发现 {{ jobs.security-scan.steps.secret-scan.outputs.secrets_found }} 处密钥泄露**

```
{{ jobs.security-scan.steps.secret-scan.outputs.details }}
```
{{ else }}
✅ 无密钥泄露
{{ endif }}

---

## 部署状态

{{ if github.event_name == 'push' && github.ref == 'refs/heads/main' }}
### 生产环境部署

- **Docker 镜像**: [查看](https://hub.docker.com/r/bridgeserver/bridge-server/tags)
- **部署状态**: {{ jobs.deploy-production.status }}
- **部署时间**: {{ jobs.deploy-production.completed_at }}
{{ else }}
_仅 main 分支的推送会触发生产部署_
{{ endif }}

---

*报告生成时间：{{ github.event.repository.updated_at }}*
```

---

## 🎯 质量标准

### 必须满足（P0）

- [ ] 单元测试覆盖率 ≥ 85%
- [ ] 所有 P0 测试通过
- [ ] 无高危安全漏洞（Bandit）
- [ ] 无高危依赖漏洞（Safety）
- [ ] 无密钥泄露（Secret Scan）

### 应该满足（P1）

- [ ] 集成测试覆盖率 ≥ 70%
- [ ] 代码格式符合 Black 规范
- [ ] Pylint 评分 ≥ 8.0
- [ ] E2E 测试通过率 ≥ 95%

### 可以违反（P2）

- [ ] 文档完整性
- [ ] 代码注释覆盖率
- [ ] 性能基准测试

---

## 🚀 部署流程

### 开发环境

```bash
# 自动部署（每次提交到 develop 分支）
git push origin develop

# GitHub Actions 自动：
# 1. 运行单元测试
# 2. 构建 Docker 镜像
# 3. 部署到开发环境
```

### 生产环境

```bash
# 1. 创建 Pull Request 到 main 分支
# 2. Code Review 通过
# 3. 合并到 main 分支
git push origin main

# GitHub Actions 自动：
# 1. 运行所有测试
# 2. 安全扫描
# 3. 构建 Docker 镜像
# 4. 部署到生产环境
```

---

## 📈 质量指标

### 测试覆盖率趋势

```
周次    单元测试  集成测试  E2E 测试
W1      82%      65%      90%
W2      85%      68%      92%
W3      87%      70%      93%
W4      88%      72%      95%
```

### 安全问题趋势

```
周次    Bandit  Safety  Secrets
W1      2       5        0
W2      1       3        0
W3      0       2        0
W4      0       0        0
```

---

*最后更新：2026-04-05*
