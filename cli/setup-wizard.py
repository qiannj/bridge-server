#!/usr/bin/env python3
"""
Bridge Server Setup Wizard v2.1

改进的配置向导：
- 循环菜单式配置
- 每个 Provider 配置后立即测试连接
- 成功才保存配置（原子性）
- 支持跳过/追加/修改
- 自定义 Provider 支持
"""

import sys
import os
import yaml
import json
import secrets
import logging
import httpx
import math
import re as _re
import time
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from config import get_default_port

# 添加 src 到路径
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.provider_catalog import ProviderLoader, Provider, Model

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_OAUTH_DEVICE_ISSUER = "https://auth.openai.com"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_CLIENT_VERSION = "1.0.0"


# ── Benchmark 常量 ─────────────────────────────────────────────────────────────

_BM_QUESTIONS_PER_DIM = 3
_BM_DIMS = 5
_BM_TOKENS_PER_CALL = 750
_BM_SECS_PER_CALL = 6

_BM_QUESTIONS: Dict[str, List[Dict]] = {
    "coding": [
        {"id": "code_1", "prompt": "用Python实现一个二分查找函数，要求：函数签名为 binary_search(arr, target)，包含详细注释，并给出时间复杂度。",
         "check": lambda r: bool(_re.search(r"def binary_search", r) and ("O(" in r or "时间复杂度" in r))},
        {"id": "code_2", "prompt": "写一段JavaScript代码，使用Promise实现一个带超时控制的fetch请求（超时3秒自动拒绝），并加注释。",
         "check": lambda r: bool(_re.search(r"Promise|fetch|timeout|setTimeout", r, _re.I))},
        {"id": "code_3", "prompt": "请找出以下Python代码中的bug并修复：\n```python\ndef find_max(lst):\n    max_val = lst[0]\n    for i in range(len(lst)):\n        if lst[i] > max_val:\n            max_val = lst[i+1]\n    return max_val\n```",
         "check": lambda r: bool(_re.search(r"lst\[i\]|索引越界|index|bug|修复|错误", r, _re.I))},
    ],
    "math": [
        {"id": "math_1", "prompt": "一列火车从A城出发，速度60km/h，同时另一列火车从B城出发，速度90km/h，两城相距600km，两车相向而行，请问几小时后相遇？给出完整解题过程。",
         "check": lambda r: bool(_re.search(r"4\s*小时|4h|4\s*hour", r, _re.I) or "4" in r)},
        {"id": "math_2", "prompt": "已知等差数列首项a₁=2，公差d=3，求第15项和前15项之和，请给出推导步骤。",
         "check": lambda r: bool(_re.search(r"44", r) and _re.search(r"345", r))},
        {"id": "math_3", "prompt": "用数学归纳法证明：对所有正整数n，1+2+3+...+n = n(n+1)/2",
         "check": lambda r: bool(_re.search(r"归纳|induction|k\+1|假设|成立", r, _re.I))},
    ],
    "writing": [
        {"id": "write_1", "prompt": "以「第一场雪」为题，写一段200字左右的散文，要求意境优美，有具体的场景描写。",
         "check": lambda r: len(r) >= 100},
        {"id": "write_2", "prompt": "帮我写一封给领导申请居家办公的邮件，原因是家中有老人生病需要照料，语气正式但不失人情味，不超过150字。",
         "check": lambda r: bool(_re.search(r"申请|敬请|居家|审批|办公|领导|尊敬", r))},
        {"id": "write_3", "prompt": "为一款主打「极简主义」风格的蓝牙耳机写一段产品介绍文案（80字以内），突出设计感和音质。",
         "check": lambda r: 20 <= len(r) <= 300},
    ],
    "translation": [
        {"id": "trans_1", "prompt": '将以下古文翻译成现代英文：\n"知之者不如好之者，好之者不如乐之者。"（出自《论语》）\n请同时给出字面意思和引申义。',
         "check": lambda r: bool(_re.search(r"know|learn|enjoy|love|delight|pleasure", r, _re.I))},
        {"id": "trans_2", "prompt": '将以下英文段落翻译成流畅的中文：\n"Artificial intelligence is transforming every industry, from healthcare to finance, creating both unprecedented opportunities and significant challenges for society."',
         "check": lambda r: bool(_re.search(r"人工智能|医疗|金融|机遇|挑战", r))},
        {"id": "trans_3", "prompt": "请将以下句子分别翻译成日语和法语：\n「春天来了，万物复苏。」",
         "check": lambda r: bool(_re.search(r"春|printemps|春が|haru", r, _re.I))},
    ],
    "chat": [
        {"id": "chat_1", "prompt": "我最近工作压力很大，经常失眠，有什么实用的放松建议？",
         "check": lambda r: len(r) >= 80 and bool(_re.search(r"放松|呼吸|运动|睡眠|休息|建议", r))},
        {"id": "chat_2", "prompt": "如果你是一种天气，你会是什么天气？为什么？（请给出有趣且有深度的回答）",
         "check": lambda r: len(r) >= 50},
        {"id": "chat_3", "prompt": "我朋友说「人生苦短，及时行乐」，我觉得这句话有点问题，你怎么看？",
         "check": lambda r: bool(_re.search(r"但|然而|不过|另一方面|平衡|责任|意义|价值", r))},
    ],
}

_BM_DIM_NAMES = {
    "coding":      "💻 代码编程",
    "math":        "🔢 数学推理",
    "writing":     "✍️  文学创作",
    "translation": "🌐 语言翻译",
    "chat":        "💬 日常对话",
}


def _bm_call_model(base_url: str, api_key: str, model_id: str,
                   prompt: str, timeout: int = 60) -> Tuple[str, float, str]:
    """Synchronous model call for benchmark. Returns (content, latency_sec, error)."""
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 1000, "temperature": 0.7}
    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout, verify=False)
        latency = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return content.strip(), latency, ""
    except httpx.TimeoutException:
        return "", time.perf_counter() - t0, f"超时（>{timeout}s）"
    except Exception as e:
        return "", time.perf_counter() - t0, str(e)[:120]


def _bm_score(content: str, latency: float, check_fn, error: str) -> Dict[str, Any]:
    if error:
        return {"score": 0, "quality": False, "latency": latency, "error": error}
    quality = bool(check_fn(content))
    q_score = 40 if quality else 0
    length = len(content)
    l_score = min(30, int(length / 500 * 30)) if length >= 20 else 0
    speed = max(0, 30 - int((latency - 5) / 85 * 30)) if latency > 5 else 30
    return {"score": q_score + l_score + speed, "quality": quality,
            "latency": round(latency, 1), "error": ""}


def _bm_stars(score: int) -> str:
    s = round(score / 20)
    return "★" * s + "☆" * (5 - s)


def run_benchmark_for_wizard(
    provider_name: str,
    base_url: str,
    api_key: str,
    model_ids: List[str],
    colors: Any,
    config_dir: Path,
) -> None:
    """Run benchmark synchronously and print results table. Called from setup wizard."""
    dims = list(_BM_QUESTIONS.keys())
    total = len(model_ids) * len(dims) * _BM_QUESTIONS_PER_DIM
    done = 0
    results: Dict[str, Dict] = {}

    for model_id in model_ids:
        key = f"{provider_name}/{model_id}"
        results[key] = {}
        for dim in dims:
            questions = _BM_QUESTIONS[dim][:_BM_QUESTIONS_PER_DIM]
            dim_scores = []
            for q in questions:
                done += 1
                pct = int(done / total * 100)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"\r  [{bar}] {pct:3d}%  {model_id}  {_BM_DIM_NAMES[dim]}",
                      end="", flush=True)
                content, latency, error = _bm_call_model(base_url, api_key, model_id, q["prompt"])
                dim_scores.append(_bm_score(content, latency, q["check"], error))
            avg_score = int(sum(r["score"] for r in dim_scores) / len(dim_scores)) if dim_scores else 0
            avg_lat = round(sum(r["latency"] for r in dim_scores) / len(dim_scores), 1) if dim_scores else 0.0
            results[key][dim] = {"score": avg_score, "stars": _bm_stars(avg_score), "avg_latency": avg_lat}
    print()  # newline after progress bar

    # ── 打印能力矩阵 ──────────────────────────────────────────────────────────
    col_w = 14
    model_col = max(24, max(len(k) for k in results) + 2)
    dim_labels = [_BM_DIM_NAMES[d] for d in dims]
    header = f"{'模型':<{model_col}}" + "".join(f"{l:^{col_w}}" for l in dim_labels) + f"{'综合':^8}"
    sep = "─" * len(header)
    print(f"\n{colors.BOLD}{colors.CYAN}{'='*len(sep)}{colors.ENDC}")
    print(f"{colors.BOLD}{colors.CYAN}  📊 模型能力矩阵{colors.ENDC}")
    print(f"{colors.CYAN}{'='*len(sep)}{colors.ENDC}\n")
    print(f"{colors.BOLD}{header}{colors.ENDC}")
    print(sep)

    for key, dim_results in sorted(results.items(),
                                   key=lambda x: -sum(v["score"] for v in x[1].values())):
        scores = [dim_results.get(d, {}).get("score", 0) for d in dims]
        overall = int(sum(scores) / len(scores)) if scores else 0
        row = f"{key:<{model_col}}"
        for d in dims:
            row += f"{dim_results.get(d,{}).get('stars','─────'):^{col_w}}"
        color = colors.GREEN if overall >= 70 else (colors.YELLOW if overall >= 50 else colors.RED)
        row += f"{color}{overall:^8}{colors.ENDC}"
        print(row)
    print(sep)

    # ── 保存结果 ─────────────────────────────────────────────────────────────
    import yaml as _yaml
    out_file = config_dir / "benchmark_results.yaml"
    existing: dict = {}
    if out_file.exists():
        with open(out_file, encoding="utf-8") as f:
            existing = _yaml.safe_load(f) or {}
    existing.setdefault("results", {}).update(results)
    existing["generated_at"] = datetime.now().isoformat()
    existing["dimensions"] = dims
    with open(out_file, "w", encoding="utf-8") as f:
        _yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
    print(f"\n{colors.GREEN}✅ 结果已保存：{out_file}{colors.ENDC}")


def _offer_benchmark_after_add(
    provider_name: str,
    base_url: str,
    api_key: str,
    model_ids: List[str],
    colors: Any,
    config_dir: Path,
) -> None:
    """Ask user if they want to run benchmark; run synchronously if yes."""
    total_calls = len(model_ids) * _BM_DIMS * _BM_QUESTIONS_PER_DIM
    est_tokens = total_calls * _BM_TOKENS_PER_CALL
    est_min = math.ceil(total_calls * _BM_SECS_PER_CALL / 60)

    print(f"\n{colors.CYAN}{'─'*60}{colors.ENDC}")
    print(f"{colors.BOLD}💡 是否现在进行模型能力摸底测试？{colors.ENDC}")
    print(f"   本测试覆盖 5 个能力维度（代码、数学、写作、翻译、对话），")
    print(f"   每个维度 {_BM_QUESTIONS_PER_DIM} 道题，每题约 500–1000 tokens。")
    print(f"\n   • 待测模型：{', '.join(model_ids)}")
    print(f"   • API 调用：{total_calls} 次")
    print(f"   • Token 消耗：约 {est_tokens:,} tokens（费用取决于各平台定价）")
    print(f"   • 预计耗时：约 {est_min} 分钟")
    print(f"\n   {colors.YELLOW}⚠️  将消耗实际 API 配额{colors.ENDC}")
    confirm = input("\n是否开始测试？[y/N]: ").strip().lower()
    if confirm != "y":
        print(f"{colors.YELLOW}已跳过，可随时在管理面板或运行 cli/model-benchmark.py 进行测试{colors.ENDC}")
        return

    print(f"\n{colors.BOLD}开始测试...（这可能需要几分钟）{colors.ENDC}\n")
    t0 = time.perf_counter()
    run_benchmark_for_wizard(provider_name, base_url, api_key, model_ids, colors, config_dir)
    elapsed = time.perf_counter() - t0
    print(f"\n{colors.GREEN}✅ 测试完成，耗时 {elapsed:.1f}s{colors.ENDC}")
    print(f"{colors.CYAN}{'─'*60}{colors.ENDC}\n")
logger = logging.getLogger(__name__)


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def select_from_list(title: str, options: list, default_index: int = 0) -> str:
    """
    终端箭头键选择菜单。
    返回选中的 option 字符串；若终端不支持 raw 模式则降级为数字输入。
    """
    import sys, os

    def _arrow_select():
        import tty, termios
        idx = default_index
        n = len(options)

        def out(s):
            sys.stdout.write(s)
            sys.stdout.flush()

        def render(first=False):
            if not first:
                # 上移 (n+1) 行回到标题行首，清屏到底
                out(f"\033[{n + 1}A\r\033[J")
            # 在 raw 模式下必须用 \r\n，不能用 print()
            out(f"  \033[36m{title}\033[0m\r\n")
            for i, opt in enumerate(options):
                if i == idx:
                    out(f"  \033[32m❯ {opt}\033[0m\r\n")
                else:
                    out(f"    {opt}\r\n")

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            render(first=True)
            while True:
                ch = sys.stdin.read(1)
                if ch in ('\r', '\n'):
                    break
                elif ch == '\x03':  # Ctrl+C
                    raise KeyboardInterrupt
                elif ch == '\x1b':  # ESC sequence
                    ch2 = sys.stdin.read(1)
                    if ch2 == '[':
                        ch3 = sys.stdin.read(1)
                        if ch3 == 'A':  # Up
                            idx = (idx - 1) % n
                        elif ch3 == 'B':  # Down
                            idx = (idx + 1) % n
                render()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out("\r\n")
        return options[idx]

    def _numeric_select():
        print(f"  {Colors.CYAN}{title}{Colors.ENDC}")
        for i, opt in enumerate(options, 1):
            marker = " (默认)" if i - 1 == default_index else ""
            print(f"  {i}. {opt}{marker}")
        while True:
            raw = input(f"  请选择 [1-{len(options)}，回车={default_index+1}]: ").strip()
            if not raw:
                return options[default_index]
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            print(f"  {Colors.RED}请输入 1-{len(options)} 之间的数字{Colors.ENDC}")

    # 仅在真实 TTY 下使用 raw 模式
    try:
        import tty, termios
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _arrow_select()
    except (ImportError, Exception):
        pass
    return _numeric_select()


class SetupWizard:
    """配置向导 v2.1"""
    
    def __init__(self):
        """初始化向导"""
        self.loader = ProviderLoader()
        self.providers = self.loader.load()
        
        # 配置数据
        self.config = {
            'version': '2.1.0',
            'server': {
                'host': '0.0.0.0',
                'port': get_default_port(),
                'debug': False
            },
            'providers': [],  # 多个提供商配置
            'routing': {
                'strategy': 'fallback',
                'timeout': 30,
                'max_retries': 3
            },
            'auth': {
                'api_keys': []
            },
            'scenarios': {}
        }
        
        # 配置目录
        config_dir_override = os.environ.get('BRIDGE_SERVER_CONFIG_DIR', '').strip()
        if config_dir_override:
            self.config_dir = Path(config_dir_override).expanduser()
        elif sys.platform == 'win32':
            self.config_dir = Path(os.environ.get('USERPROFILE', '')) / '.bridge-server'
        else:
            self.config_dir = Path.home() / '.bridge-server'
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.env_path = self.config_dir / '.env'
        
        # 加载现有配置（如果存在）
        self._load_existing_config()
    
    def _load_existing_config(self):
        """加载现有配置"""
        config_path = self.config_dir / 'config.yaml'
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    existing = yaml.safe_load(f)
                    if existing:
                        self.config.update(self._normalize_existing_config(existing))
                        print(f"{Colors.GREEN}✓ 已加载现有配置{Colors.ENDC}")
            except Exception as e:
                logger.warning(f"加载配置失败：{e}")
        
        # 加载现有环境变量
        if self.env_path.exists():
            with open(self.env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip()

    def _normalize_existing_config(self, existing: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧版配置结构，避免配置向导因历史格式崩溃。"""
        normalized = dict(existing)
        providers = normalized.get('providers', [])

        if isinstance(providers, dict):
            converted_providers = []
            for provider_name, provider_data in providers.items():
                if not isinstance(provider_data, dict):
                    continue

                models_data = provider_data.get('models', {})
                converted_models = []

                if isinstance(models_data, dict):
                    for priority, (model_id, model_meta) in enumerate(models_data.items(), start=1):
                        model_name = model_id
                        if isinstance(model_meta, dict):
                            model_name = model_meta.get('name') or model_meta.get('alias') or model_id
                        converted_models.append({
                            'id': model_id,
                            'name': model_name,
                            'priority': priority,
                        })
                elif isinstance(models_data, list):
                    for priority, model in enumerate(models_data, start=1):
                        if isinstance(model, dict):
                            converted_models.append({
                                'id': model.get('id', model.get('name', f'model-{priority}')),
                                'name': model.get('name', model.get('id', f'model-{priority}')),
                                'priority': model.get('priority', priority),
                            })
                        else:
                            converted_models.append({
                                'id': str(model),
                                'name': str(model),
                                'priority': priority,
                            })

                converted_provider = {
                    'name': provider_data.get('name') or provider_name,
                    'api_key_env': provider_data.get('api_key_env', f"{provider_name.upper().replace('-', '_')}_API_KEY"),
                    'base_url': provider_data.get('base_url', ''),
                    'models': converted_models,
                }
                converted_providers.append(converted_provider)

            normalized['providers'] = converted_providers

        elif not isinstance(providers, list):
            normalized['providers'] = []

        return normalized
    
    def run(self):
        """运行配置向导"""
        self._print_header()
        
        try:
            # 主循环：配置 Provider
            self._provider_menu()
            
            # 配置场景化模型
            self._configure_scenarios()
            
            # 选择路由策略
            self._select_routing()
            
            # 生成认证信息
            self._generate_auth()
            
            # 保存并启动
            self._save_and_start()
            
        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}⚠️  配置已取消{Colors.ENDC}")
            sys.exit(0)
        except Exception as e:
            print(f"\n{Colors.RED}❌ 错误：{e}{Colors.ENDC}")
            logger.exception("配置向导异常")
            sys.exit(1)
    
    def _print_header(self):
        """打印欢迎头"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.CYAN}  Bridge Server 配置向导 v2.1{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"\n{Colors.GREEN}👋 欢迎使用 Bridge Server 快速配置工具！{Colors.ENDC}")
        print(f"\n新功能：")
        print(f"  ✅ 循环菜单式配置，随时可修改")
        print(f"  ✅ 每个 Provider 配置后立即测试连接")
        print(f"  ✅ 成功才保存配置（原子性）")
        print(f"  ✅ 支持自定义 Provider (Base URL + 模型)")
        print(f"  ✅ 场景化模型推荐 (Coding/Writing/Search/Summary)")
        print(f"\n{Colors.YELLOW}提示：使用 Ctrl+C 可随时退出{Colors.ENDC}\n")
    
    def _provider_menu(self):
        """Provider 配置主菜单"""
        while True:
            print(f"\n{Colors.BOLD}🏢 Provider 配置菜单{Colors.ENDC}")
            print(f"{'-'*60}")
            
            # 显示已配置的 Provider
            if self.config['providers']:
                print(f"\n{Colors.GREEN}已配置的 Provider:{Colors.ENDC}")
                for i, p in enumerate(self.config['providers'], 1):
                    name = p.get('name', 'Unknown')
                    models = p.get('models', [])
                    model_count = len(models) if isinstance(models, list) else 0
                    print(f"  {i}. {name} ({model_count} 个模型)")
            else:
                print(f"\n{Colors.YELLOW}⚠️  尚未配置任何 Provider{Colors.ENDC}")
            
            print(f"\n{Colors.CYAN}请选择操作:{Colors.ENDC}")
            print(f"  1. 添加预设 Provider (阿里云/OpenAI/等)")
            print(f"  2. 添加自定义 Provider (Base URL + 模型)")
            if self.config['providers']:
                print(f"  3. 修改已有 Provider")
                print(f"  4. 删除已有 Provider")
            print(f"  5. 完成 Provider 配置，继续下一步")
            print(f"  0. 跳过/不修改，保持当前状态")
            
            choice = input(f"\n请选择 [0-5]: ").strip()
            
            if choice == '1':
                self._add_preset_provider()
            elif choice == '2':
                self._add_custom_provider()
            elif choice == '3':
                if self.config['providers']:
                    self._modify_provider()
                else:
                    print(f"{Colors.YELLOW}⚠️  暂无可修改的 Provider{Colors.ENDC}")
            elif choice == '4':
                if self.config['providers']:
                    self._delete_provider()
                else:
                    print(f"{Colors.YELLOW}⚠️  暂无可删除的 Provider{Colors.ENDC}")
            elif choice == '5':
                if not self.config['providers']:
                    print(f"{Colors.RED}❌ 至少配置一个 Provider 才能继续{Colors.ENDC}")
                else:
                    break
            elif choice == '0':
                if not self.config['providers']:
                    print(f"{Colors.RED}❌ 至少配置一个 Provider 才能继续{Colors.ENDC}")
                else:
                    break
            else:
                print(f"{Colors.RED}请输入 0-5 之间的数字{Colors.ENDC}")
    
    def _add_preset_provider(self):
        """添加预设 Provider"""
        print(f"\n{Colors.BOLD}选择预设 Provider{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # 显示可用 Provider
        providers_list = list(self.providers.values())
        for i, p in enumerate(providers_list, 1):
            print(f"  {i}. {p.name} ({p.name_en})")
        
        choice = input(f"\n请选择 [1-{len(providers_list)}] (回车返回): ").strip()
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if not (0 <= idx < len(providers_list)):
            print(f"{Colors.RED}无效选择{Colors.ENDC}")
            return
        
        provider = providers_list[idx]
        
        print(f"\n配置 {provider.name}:")
        print(f"  Base URL: {provider.base_url}")

        # ── 认证方式选择 ──────────────────────────────────────────────────────
        auth_type = self._choose_auth_type(provider)

        if auth_type in {"oauth", "openai_codex"}:
            oauth_cfg = self._collect_oauth_config(auth_type=auth_type, provider_name=provider.name)
            if not oauth_cfg:
                print(f"{Colors.YELLOW}⚠️  已取消{Colors.ENDC}")
                return
        else:
            print(f"  环境变量：{provider.api_key_env}")
            print(f"  获取地址：{provider.api_key_url}\n")
            api_key = input(f"请输入 API Key (回车返回): ").strip()
            if not api_key:
                return

        # 配置模型
        models = self._add_models_loop(
            provider,
            auth_type=auth_type,
            oauth_cfg=oauth_cfg if auth_type in {"oauth", "openai_codex"} else None,
            api_key=api_key if auth_type == "api_key" else None,
        )
        if not models:
            print(f"{Colors.RED}❌ 至少添加一个模型{Colors.ENDC}")
            return
        
        # 测试连接
        print(f"\n{Colors.CYAN}测试连接...{Colors.ENDC}")
        if auth_type in {"oauth", "openai_codex"}:
            runtime_base_url = oauth_cfg.get('base_url', provider.base_url)
            success = self._test_oauth_connection(runtime_base_url, oauth_cfg, models[0]['id'])
        else:
            success = self._test_provider_connection(provider.base_url, api_key, models[0]['id'])
        
        if success:
            if auth_type in {"oauth", "openai_codex"}:
                provider_config = {
                    'name': provider.name,
                    'base_url': oauth_cfg.get('base_url', provider.base_url),
                    'auth_type': 'oauth',
                    'oauth': oauth_cfg,
                    'models': models,
                }
            else:
                provider_config = {
                    'name': provider.name,
                    'api_key_env': provider.api_key_env,
                    'base_url': provider.base_url,
                    'models': models,
                }
                self._save_env_var(provider.api_key_env, api_key)

            self.config['providers'].append(provider_config)
            print(f"{Colors.GREEN}✅ {provider.name} 配置成功并已保存！{Colors.ENDC}")
            # 邀约进行能力测试
            _bm_key = api_key if auth_type == "api_key" else (self._fetch_oauth_token(oauth_cfg) or "")
            model_ids = [m.get('id', '') if isinstance(m, dict) else str(m) for m in models]
            _offer_benchmark_after_add(
                provider.name, provider_config['base_url'], _bm_key,
                model_ids, Colors, self.config_dir,
            )
        else:
            print(f"{Colors.RED}❌ 连接测试失败，配置未保存{Colors.ENDC}")
            retry = input("是否跳过连接测试，强制保存？[y/N]: ").strip().lower()
            if retry == 'y':
                if auth_type in {"oauth", "openai_codex"}:
                    provider_config = {
                        'name': provider.name,
                        'base_url': oauth_cfg.get('base_url', provider.base_url),
                        'auth_type': 'oauth',
                        'oauth': oauth_cfg,
                        'models': models,
                    }
                else:
                    provider_config = {
                        'name': provider.name,
                        'api_key_env': provider.api_key_env,
                        'base_url': provider.base_url,
                        'models': models,
                    }
                    self._save_env_var(provider.api_key_env, api_key)
                self.config['providers'].append(provider_config)
                print(f"{Colors.YELLOW}⚠️  {provider.name} 已强制保存（连接未验证）{Colors.ENDC}")

    def _add_custom_provider(self):
        """添加自定义 Provider"""
        print(f"\n{Colors.BOLD}自定义 Provider{Colors.ENDC}")
        print(f"{'-'*60}\n")

        # Provider 名称
        name = input("Provider 名称 (如 my-llm): ").strip()
        if not name:
            return

        # Base URL
        base_url = input("API Base URL (如 https://api.example.com/v1): ").strip()
        if not base_url:
            return

        # ── 认证方式选择 ──────────────────────────────────────────────────────
        auth_type = self._choose_auth_type(base_url=base_url)

        if auth_type in {"oauth", "openai_codex"}:
            oauth_cfg = self._collect_oauth_config(auth_type=auth_type, provider_name=name)
            if not oauth_cfg:
                print(f"{Colors.YELLOW}⚠️  已取消{Colors.ENDC}")
                return
        else:
            # 标准 API Key
            api_key_env = f"{name.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
            print(f"环境变量名（自动生成）：{Colors.CYAN}{api_key_env}{Colors.ENDC}")
            api_key = input(f"请输入 API Key: ").strip()
            if not api_key:
                return

        # 配置模型
        print(f"\n添加模型 (每次一个，空行结束):")
        models = []
        model_idx = 1
        while True:
            model_id = input(f"  模型{model_idx} ID: ").strip()
            if not model_id:
                break
            model_name = input(f"  模型{model_idx} 昵称 (回车同 ID): ").strip()
            if not model_name:
                model_name = model_id
            models.append({'id': model_id, 'name': model_name, 'priority': model_idx})
            model_idx += 1

        if not models:
            print(f"{Colors.RED}❌ 至少添加一个模型{Colors.ENDC}")
            return

        # ── 测试连接 ──────────────────────────────────────────────────────────
        print(f"\n{Colors.CYAN}测试连接...{Colors.ENDC}")
        if auth_type in {"oauth", "openai_codex"}:
            runtime_base_url = oauth_cfg.get('base_url', base_url)
            success = self._test_oauth_connection(runtime_base_url, oauth_cfg, models[0]['id'])
        else:
            success = self._test_provider_connection(base_url, api_key, models[0]['id'])

        if success:
            if auth_type in {"oauth", "openai_codex"}:
                provider_config = {
                    'name': name,
                    'base_url': oauth_cfg.get('base_url', base_url),
                    'auth_type': 'oauth',
                    'oauth': oauth_cfg,
                    'models': models,
                }
            else:
                provider_config = {
                    'name': name,
                    'api_key_env': api_key_env,
                    'base_url': base_url,
                    'models': models,
                }
                self._save_env_var(api_key_env, api_key)

            self.config['providers'].append(provider_config)
            print(f"{Colors.GREEN}✅ {name} 配置成功并已保存！{Colors.ENDC}")
            # 邀约进行能力测试
            _bm_key = api_key if auth_type == "api_key" else (self._fetch_oauth_token(oauth_cfg) or "")
            model_ids = [m.get('id', '') if isinstance(m, dict) else str(m) for m in models]
            _offer_benchmark_after_add(
                name, provider_config['base_url'], _bm_key,
                model_ids, Colors, self.config_dir,
            )
        else:
            print(f"{Colors.RED}❌ 连接测试失败，配置未保存{Colors.ENDC}")
            retry = input("是否跳过连接测试，强制保存？[y/N]: ").strip().lower()
            if retry == 'y':
                if auth_type in {"oauth", "openai_codex"}:
                    provider_config = {
                        'name': name,
                        'base_url': oauth_cfg.get('base_url', base_url),
                        'auth_type': 'oauth',
                        'oauth': oauth_cfg,
                        'models': models,
                    }
                else:
                    provider_config = {
                        'name': name,
                        'api_key_env': api_key_env,
                        'base_url': base_url,
                        'models': models,
                    }
                    self._save_env_var(api_key_env, api_key)
                self.config['providers'].append(provider_config)
                print(f"{Colors.YELLOW}⚠️  {name} 已强制保存（连接未验证）{Colors.ENDC}")
    
    def _normalize_dynamic_model(self, raw: Dict[str, Any]) -> Optional[Model]:
        """Normalize remote-discovered model metadata into the local Model shape."""
        model_id = str(raw.get("slug") or raw.get("id") or "").strip()
        if not model_id:
            return None

        visibility = str(raw.get("visibility") or "").strip().lower()
        if visibility and visibility not in {"list", "default", "public"}:
            return None
        if raw.get("supported_in_api") is False:
            return None

        display_name = str(raw.get("display_name") or raw.get("name") or model_id).strip()
        description = str(raw.get("description") or "动态发现的远端模型").strip()
        context_length = int(raw.get("context_window") or raw.get("max_context_window") or 0)
        truncation = raw.get("truncation_policy") or {}
        max_output_tokens = int(truncation.get("limit") or raw.get("max_output_tokens") or 0)

        capabilities: List[str] = []
        for modality in raw.get("input_modalities") or []:
            text = str(modality).strip()
            if text:
                capabilities.append(text)
        if raw.get("supported_reasoning_levels"):
            capabilities.append("reasoning")

        return Model(
            id=model_id,
            name=display_name,
            description=description,
            context_length=context_length,
            max_output_tokens=max_output_tokens,
            pricing=None,
            capabilities=capabilities,
            provider="openai",
        )

    def _fetch_openai_codex_models(
        self,
        oauth_cfg: Dict[str, Any],
        base_url: str = CODEX_BASE_URL,
    ) -> List[Model]:
        """Fetch the model catalog from the Codex backend for browser-auth sessions."""
        token = self._fetch_oauth_token(oauth_cfg)
        if not token:
            return []

        base = (base_url or CODEX_BASE_URL).rstrip("/")
        url = f"{base}/models"
        print(f"  🔍 正在从远端拉取模型目录：GET {url}?client_version={CODEX_CLIENT_VERSION}")
        try:
            response = httpx.get(
                url,
                params={"client_version": CODEX_CLIENT_VERSION},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "BridgeServer/2.0",
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"  {Colors.YELLOW}⚠️  动态拉取模型目录失败，回退到本地预设：{exc}{Colors.ENDC}")
            return []

        raw_models = payload.get("models") or []
        models: List[Model] = []
        seen_ids = set()
        for raw in raw_models:
            if not isinstance(raw, dict):
                continue
            model = self._normalize_dynamic_model(raw)
            if not model or model.id in seen_ids:
                continue
            seen_ids.add(model.id)
            models.append(model)

        if models:
            print(f"  {Colors.GREEN}✓ 已从远端拉取 {len(models)} 个可用模型{Colors.ENDC}")
        else:
            print(f"  {Colors.YELLOW}⚠️  远端未返回可展示模型，回退到本地预设{Colors.ENDC}")
        return models

    def _resolve_models_for_selection(
        self,
        provider: Provider,
        auth_type: str = "api_key",
        oauth_cfg: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
    ) -> Tuple[List[Model], str]:
        """Return model choices plus a user-facing source label."""
        provider_models = list(provider.models.values()) if isinstance(provider.models, dict) else list(provider.models)

        if auth_type == "openai_codex" and oauth_cfg:
            base_url = str(oauth_cfg.get("base_url") or getattr(provider, "base_url", "") or CODEX_BASE_URL)
            dynamic_models = self._fetch_openai_codex_models(oauth_cfg, base_url=base_url)
            if dynamic_models:
                return dynamic_models, "远端实时返回"
            return provider_models, "本地预设（动态拉取失败后回退）"

        return provider_models, "本地预设"

    def _add_models_loop(
        self,
        provider: Provider,
        auth_type: str = "api_key",
        oauth_cfg: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
    ) -> List[Dict]:
        """循环添加模型"""
        print(f"\n{provider.name} 可用模型:")

        models_list, source_label = self._resolve_models_for_selection(
            provider,
            auth_type=auth_type,
            oauth_cfg=oauth_cfg,
            api_key=api_key,
        )
        print(f"  来源：{source_label}")
        
        # 显示前 20 个模型
        for i, m in enumerate(models_list[:20], 1):
            price = f"¥{m.pricing.input_per_1k}/1K" if m.pricing else "N/A"
            print(f"  {i}. {m.name} (ctx: {m.context_length}, price: {price})")
        
        if len(models_list) > 20:
            print(f"  ... 还有 {len(models_list) - 20} 个模型")
        
        print(f"\n添加模型 (每次一个，空行结束):")
        print(f"  输入编号选择预设模型，或直接输入模型 ID")
        
        models = []
        model_idx = 1
        while True:
            choice = input(f"  模型{model_idx}: ").strip()
            if not choice:
                break
            
            # 检查是否是编号
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(models_list):
                    model = models_list[idx]
                    models.append({
                        'id': model.id,
                        'name': model.name,
                        'priority': model_idx
                    })
                    print(f"    ✓ 已添加：{model.name} ({model.id})")
                else:
                    print(f"    {Colors.RED}无效编号{Colors.ENDC}")
            else:
                # 自定义模型 ID
                model_name = input(f"    昵称 (回车同 ID): ").strip()
                if not model_name:
                    model_name = choice
                models.append({
                    'id': choice,
                    'name': model_name,
                    'priority': model_idx
                })
                print(f"    ✓ 已添加：{choice} ({model_name})")
            
            model_idx += 1
        
        return models
    
    def _test_provider_connection(self, base_url: str, api_key: str, model_id: str) -> bool:
        """测试 Provider 连接"""
        try:
            # 若 base_url 已以 /chat/completions 结尾则直接使用，否则拼接
            stripped = base_url.rstrip('/')
            if stripped.endswith('/chat/completions'):
                test_url = stripped
            else:
                test_url = stripped + '/chat/completions'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            }
            data = {
                'model': model_id,
                'messages': [
                    {'role': 'user', 'content': 'Hi'}
                ],
                'max_tokens': 1
            }
            
            print(f"  请求：POST {test_url}")
            print(f"  模型：{model_id}")
            
            # 先尝试正常 SSL 验证，失败后自动降级（企业代理场景）
            try:
                response = httpx.post(test_url, json=data, headers=headers, timeout=10)
            except httpx.ConnectError as ssl_err:
                if 'CERTIFICATE_VERIFY_FAILED' in str(ssl_err) or 'SSL' in str(ssl_err).upper():
                    print(f"  {Colors.YELLOW}⚠ SSL 验证失败（企业代理），尝试跳过证书验证...{Colors.ENDC}")
                    response = httpx.post(test_url, json=data, headers=headers, timeout=10, verify=False)
                else:
                    raise
            
            if response.status_code == 200:
                print(f"  {Colors.GREEN}✓ 连接成功 (HTTP {response.status_code}){Colors.ENDC}")
                return True
            else:
                print(f"  {Colors.RED}✗ 连接失败 (HTTP {response.status_code}): {response.text[:100]}{Colors.ENDC}")
                return False
                
        except httpx.TimeoutException:
            print(f"  {Colors.RED}✗ 连接超时 (10 秒){Colors.ENDC}")
            return False
        except Exception as e:
            print(f"  {Colors.RED}✗ 连接错误：{e}{Colors.ENDC}")
            return False
    
    def _modify_provider(self):
        """修改已有 Provider"""
        if not self.config['providers']:
            print(f"{Colors.RED}没有可修改的 Provider{Colors.ENDC}")
            return
        
        print(f"\n选择要修改的 Provider:")
        for i, p in enumerate(self.config['providers'], 1):
            print(f"  {i}. {p.get('name', 'Unknown')}")
        
        choice = input(f"请选择 [1-{len(self.config['providers'])}] (回车返回): ").strip()
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if not (0 <= idx < len(self.config['providers'])):
            print(f"{Colors.RED}无效选择{Colors.ENDC}")
            return
        
        # 删除旧的，重新添加
        provider = self.config['providers'].pop(idx)
        print(f"\n已移除 {provider['name']}，请重新配置:\n")
        
        # 根据是否有 base_url 判断是预设还是自定义
        if 'base_url' in provider and provider.get('name') not in [p.name for p in self.providers.values()]:
            self._add_custom_provider()
        else:
            self._add_preset_provider()
    
    def _delete_provider(self):
        """删除 Provider"""
        if not self.config['providers']:
            print(f"{Colors.RED}没有可删除的 Provider{Colors.ENDC}")
            return
        
        print(f"\n选择要删除的 Provider:")
        for i, p in enumerate(self.config['providers'], 1):
            print(f"  {i}. {p.get('name', 'Unknown')}")
        
        choice = input(f"请选择 [1-{len(self.config['providers'])}] (回车返回): ").strip()
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if not (0 <= idx < len(self.config['providers'])):
            print(f"{Colors.RED}无效选择{Colors.ENDC}")
            return
        
        provider = self.config['providers'].pop(idx)
        print(f"{Colors.GREEN}✓ 已删除 {provider['name']}{Colors.ENDC}")
    
    def _choose_auth_type(self, provider: Optional[Any] = None, base_url: str = "") -> str:
        """让用户选择认证方式。"""
        print(f"\n{Colors.CYAN}选择认证方式:{Colors.ENDC}")
        options = ["🔑 API Key（标准 Bearer Token）", "🔐 OAuth 2.0 Client Credentials"]

        provider_id = str(getattr(provider, "id", "") or "").strip().lower()
        provider_name = str(getattr(provider, "name", "") or "").strip().lower()
        resolved_base_url = (base_url or str(getattr(provider, "base_url", "") or "")).strip().lower()
        is_openai = provider_id == "openai" or provider_name == "openai" or "chatgpt.com/backend-api/codex" in resolved_base_url
        if is_openai:
            options.insert(1, "🧠 ChatGPT 账号授权（OpenAI Codex OAuth）")

        auth_type = select_from_list(
            "认证方式（↑↓ 移动，Enter 确认）",
            options,
            default_index=0,
        )
        if "ChatGPT 账号授权" in auth_type:
            return "openai_codex"
        return "oauth" if "OAuth" in auth_type else "api_key"

    def _collect_oauth_config(self, auth_type: str = "oauth", provider_name: str = "") -> Optional[Dict[str, Any]]:
        """收集 OAuth 配置。"""
        if auth_type == "openai_codex":
            return self._collect_openai_codex_oauth_config(provider_name=provider_name or "openai")

        print(f"\n{Colors.BOLD}OAuth 2.0 配置{Colors.ENDC}")
        print(f"  grant_type 固定为 client_credentials（标准企业 SSO 场景）\n")

        token_url = input("  Token URL (如 https://oauth.example.com/token): ").strip()
        if not token_url:
            return None

        client_id = input("  Client ID: ").strip()
        if not client_id:
            return None

        client_secret = input("  Client Secret: ").strip()
        if not client_secret:
            return None

        scope = input("  Scope (可选，空格分隔，回车跳过): ").strip()

        cfg: Dict[str, Any] = {
            "token_url": token_url,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scope:
            cfg["scope"] = scope
        return cfg

    def _auth_store_path(self) -> Path:
        return self.config_dir / 'auth.json'

    def _save_oauth_auth_store(self, key: str, auth_payload: Dict[str, Any]) -> None:
        path = self._auth_store_path()
        data: Dict[str, Any] = {}
        if path.exists():
            raw = path.read_text(encoding='utf-8')
            try:
                data = json.loads(raw)
            except Exception:
                try:
                    parsed = yaml.safe_load(raw) or {}
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception:
                    data = {}
        providers = data.setdefault('providers', {})
        providers[key] = auth_payload
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        if os.name != 'nt':
            os.chmod(path, 0o600)

    def _is_remote_session(self) -> bool:
        return bool(os.getenv('SSH_CLIENT') or os.getenv('SSH_TTY'))

    def _run_openai_codex_oauth_login(self) -> Dict[str, Any]:
        issuer = CODEX_OAUTH_DEVICE_ISSUER

        try:
            resp = httpx.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
        except Exception as exc:
            raise RuntimeError(f"OpenAI Codex 设备码申请失败：{exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI Codex 设备码申请失败：HTTP {resp.status_code}")

        device_data = resp.json()
        user_code = str(device_data.get("user_code", "") or "").strip()
        device_auth_id = str(device_data.get("device_auth_id", "") or "").strip()
        poll_interval = max(3, int(device_data.get("interval", 5) or 5))
        if not user_code or not device_auth_id:
            raise RuntimeError("OpenAI Codex 设备码响应缺少 user_code 或 device_auth_id")

        verification_url = f"{issuer}/codex/device"
        print(f"\n{Colors.BOLD}OpenAI Codex / ChatGPT OAuth 登录{Colors.ENDC}")
        print("  1. 用浏览器打开下面这个地址：")
        print(f"     {Colors.CYAN}{verification_url}{Colors.ENDC}")
        print("  2. 请使用你的 ChatGPT 账号登录")
        print(f"  3. 输入授权码：{Colors.YELLOW}{user_code}{Colors.ENDC}")
        print("  4. 授权完成后回到终端，程序会自动继续\n")

        if not self._is_remote_session():
            try:
                opened = webbrowser.open(verification_url)
                if opened:
                    print(f"  {Colors.GREEN}✓ 已尝试自动打开浏览器{Colors.ENDC}")
            except Exception:
                pass

        print("等待授权完成...（Ctrl+C 可取消）")
        deadline = time.monotonic() + 15 * 60
        code_resp = None
        poll_start = time.monotonic()
        last_dot = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            # Show elapsed time every ~10 seconds
            now = time.monotonic()
            if now - last_dot >= 10:
                elapsed = int(now - poll_start)
                print(f"  ⏳ 已等待 {elapsed}s，还剩 {max(0, 900 - elapsed)}s ...", flush=True)
                last_dot = now
            poll_resp = httpx.post(
                f"{issuer}/api/accounts/deviceauth/token",
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if poll_resp.status_code == 200:
                code_resp = poll_resp.json()
                break
            if poll_resp.status_code in (403, 404):
                continue
            raise RuntimeError(f"OpenAI Codex 轮询失败：HTTP {poll_resp.status_code}")

        if code_resp is None:
            raise RuntimeError("OpenAI Codex 登录超时（15 分钟）")

        authorization_code = str(code_resp.get("authorization_code", "") or "").strip()
        code_verifier = str(code_resp.get("code_verifier", "") or "").strip()
        if not authorization_code or not code_verifier:
            raise RuntimeError("OpenAI Codex 授权响应缺少 authorization_code 或 code_verifier")

        print("  🔄 交换 Token 中...", flush=True)
        token_resp = httpx.post(
            CODEX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": f"{issuer}/deviceauth/callback",
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if token_resp.status_code != 200:
            raise RuntimeError(f"OpenAI Codex Token 交换失败：HTTP {token_resp.status_code}")

        token_payload = token_resp.json()
        access_token = str(token_payload.get("access_token", "") or "").strip()
        refresh_token = str(token_payload.get("refresh_token", "") or "").strip()
        if not access_token or not refresh_token:
            raise RuntimeError("OpenAI Codex Token 响应缺少 access_token 或 refresh_token")

        expires_in = int(token_payload.get("expires_in", 3600) or 3600)
        expires_at_unix = time.time() + expires_in

        return {
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at_unix,
            },
            "expires_in": expires_in,
            "base_url": CODEX_BASE_URL,
            "last_refresh": datetime.now(tz=None).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _collect_openai_codex_oauth_config(self, provider_name: str = 'openai') -> Optional[Dict[str, Any]]:
        auth_store_key = provider_name.strip() or 'openai'

        # Check if tokens already exist and are still valid
        existing = self._load_existing_codex_tokens(auth_store_key)
        if existing:
            expires_at = existing.get('expires_at', 0)
            remaining = expires_at - time.time() if expires_at else 0
            if remaining > 120:
                mins = int(remaining // 60)
                print(f"\n{Colors.GREEN}✓ 检测到已有有效的 OpenAI Codex 登录状态（剩余约 {mins} 分钟）{Colors.ENDC}")
                reuse = input("  是否跳过重新登录？[Y/n]: ").strip().lower()
                if reuse != 'n':
                    return {
                        'provider': 'openai_codex',
                        'auth_store_key': auth_store_key,
                        'client_id': CODEX_OAUTH_CLIENT_ID,
                        'token_url': CODEX_OAUTH_TOKEN_URL,
                        'grant_type': 'refresh_token',
                        'base_url': CODEX_BASE_URL,
                    }

        try:
            login_result = self._run_openai_codex_oauth_login()
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}⚠️  已取消{Colors.ENDC}")
            return None
        except Exception as exc:
            print(f"{Colors.RED}✗ OpenAI Codex OAuth 登录失败：{exc}{Colors.ENDC}")
            return None

        self._save_oauth_auth_store(
            auth_store_key,
            {
                'provider': 'openai_codex',
                'tokens': login_result['tokens'],
                'last_refresh': login_result.get('last_refresh'),
                'base_url': login_result.get('base_url', CODEX_BASE_URL),
            },
        )

        expires_in = login_result.get('expires_in', 3600)
        mins = expires_in // 60
        print(f"{Colors.GREEN}✓ OpenAI Codex OAuth 登录成功，凭据已保存（Token 有效期约 {mins} 分钟）{Colors.ENDC}")
        print(f"  📁 存储路径：{self._auth_store_path()}")

        oauth_cfg = {
            'provider': 'openai_codex',
            'auth_store_key': auth_store_key,
            'client_id': CODEX_OAUTH_CLIENT_ID,
            'token_url': CODEX_OAUTH_TOKEN_URL,
            'grant_type': 'refresh_token',
            'base_url': login_result.get('base_url', CODEX_BASE_URL),
        }

        # Quick connectivity test using the freshly issued token
        print("  🔍 验证 Token 连通性...", flush=True)
        token = self._fetch_oauth_token(oauth_cfg)
        if not token:
            print(f"{Colors.YELLOW}⚠️  Token 获取验证失败，请检查网络或稍后重试{Colors.ENDC}")

        return oauth_cfg

    def _load_existing_codex_tokens(self, auth_store_key: str) -> Optional[Dict]:
        """Return token dict from auth store if it has a refresh_token, else None."""
        path = self._auth_store_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            provider_state = (data.get('providers') or {}).get(auth_store_key) or {}
            tokens = provider_state.get('tokens') or {}
            if tokens.get('refresh_token'):
                return tokens
        except Exception:
            pass
        return None

    def _fetch_oauth_token(self, oauth_cfg: Dict[str, Any]) -> Optional[str]:
        """获取 OAuth access_token，失败返回 None。"""
        if oauth_cfg.get('provider') == 'openai_codex':
            try:
                # Import the module directly to avoid triggering heavy
                # bridge_server.providers.__init__ chain (needs structlog etc.)
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location(
                    "oauth_manager",
                    os.path.join(REPO_ROOT, "src", "bridge_server", "providers", "oauth_manager.py"),
                )
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                OAuthTokenManager = _mod.OAuthTokenManager
                OAuthTokenRevokedException = _mod.OAuthTokenRevokedException

                manager = OAuthTokenManager(
                    token_url=oauth_cfg['token_url'],
                    client_id=oauth_cfg['client_id'],
                    provider='openai_codex',
                    auth_store_key=oauth_cfg['auth_store_key'],
                )
                token = manager.get_cached_token_sync()
                if token:
                    print(f"  {Colors.GREEN}✓ OAuth Token 获取成功{Colors.ENDC}")
                    return token
            except Exception as e:
                if 'revoked' in str(type(e).__name__).lower() or 'revoked' in str(e).lower():
                    print(f"  {Colors.RED}✗ Refresh Token 已失效，请重新运行 setup-wizard 登录{Colors.ENDC}")
                else:
                    print(f"  {Colors.RED}✗ OAuth 请求失败：{e}{Colors.ENDC}")
                return None

        data = {
            "grant_type": "client_credentials",
            "client_id": oauth_cfg["client_id"],
            "client_secret": oauth_cfg["client_secret"],
        }
        if oauth_cfg.get("scope"):
            data["scope"] = oauth_cfg["scope"]

        try:
            resp = httpx.post(oauth_cfg["token_url"], data=data, timeout=10)
            if resp.status_code == 200:
                token = resp.json().get("access_token")
                if token:
                    print(f"  {Colors.GREEN}✓ OAuth Token 获取成功{Colors.ENDC}")
                    return token
            print(f"  {Colors.RED}✗ Token 获取失败 (HTTP {resp.status_code}): {resp.text[:150]}{Colors.ENDC}")
            return None
        except Exception as e:
            print(f"  {Colors.RED}✗ OAuth 请求失败：{e}{Colors.ENDC}")
            return None

    def _test_oauth_connection(self, base_url: str, oauth_cfg: Dict[str, Any], model_id: str) -> bool:
        """先获取 OAuth token，再测试 API 连通性。"""
        print(f"  获取 OAuth Token...")
        token = self._fetch_oauth_token(oauth_cfg)
        if not token:
            return False
        return self._test_provider_connection(base_url, token, model_id)

    def _save_env_var(self, name: str, value: str):
        """保存环境变量到 .env 文件"""
        env_content = {}
        if self.env_path.exists():
            with open(self.env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env_content[k.strip()] = v.strip()
        
        env_content[name] = value
        
        with open(self.env_path, 'w') as f:
            f.write(f"# Bridge Server 环境变量\n")
            f.write(f"# 生成时间：{datetime.now().isoformat()}\n\n")
            for k, v in env_content.items():
                f.write(f"{k}={v}\n")
    
    def _configure_scenarios(self):
        """配置场景化模型 - 箭头键选择菜单"""
        print(f"\n{Colors.BOLD}🎯 步骤 2/4: 配置场景化模型{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        use_scenarios = input("是否配置场景化模型？[y/N]: ").strip().lower()
        if use_scenarios != 'y':
            print(f"\n{Colors.YELLOW}⚠️  已跳过{Colors.ENDC}")
            return
        
        # 收集所有已配置的模型 ID（provider/model_id 格式）
        available_models = []
        for provider in self.config['providers']:
            provider_name = provider.get('name', 'unknown')
            models = provider.get('models', [])
            if isinstance(models, list):
                for model in models:
                    model_id = model.get('id', '') if isinstance(model, dict) else str(model)
                    available_models.append(f"{provider_name}/{model_id}")
            elif isinstance(models, dict):
                for model_id in models.keys():
                    available_models.append(f"{provider_name}/{model_id}")
        
        if not available_models:
            print(f"{Colors.RED}❌ 没有可用的模型，请先配置 Provider{Colors.ENDC}")
            return
        
        scenarios = [
            ('coding',      '💻 编程辅助',  '代码生成、调试'),
            ('writing',     '✍️  写作创作',  '文章、邮件'),
            ('search',      '🔍 搜索分析',  '信息检索'),
            ('summary',     '📝 摘要总结',  '长文摘要'),
            ('chat',        '💬 日常对话',  '聊天问答'),
            ('translation', '🌐 翻译',      '多语言互译'),
        ]
        
        for key, name, desc in scenarios:
            print(f"\n{Colors.BOLD}{name}  ({desc}){Colors.ENDC}")
            # 当前已保存的值作为默认
            current = self.config.get('scenarios', {}).get(key, {}).get('model', available_models[0])
            default_idx = available_models.index(current) if current in available_models else 0
            chosen = select_from_list(f"选择模型（↑↓ 移动，Enter 确认）", available_models, default_idx)
            self.config['scenarios'][key] = {'enabled': True, 'model': chosen}
            print(f"  {Colors.GREEN}✓ 已选择：{chosen}{Colors.ENDC}")
        
        print(f"\n{Colors.GREEN}✅ 场景化模型配置完成{Colors.ENDC}")
        print(f"   提示：场景配置只允许选择已配置的具体模型，避免路由配置自引用")
    
    def _select_routing(self):
        """选择路由策略"""
        print(f"\n{Colors.BOLD}🔀 步骤 3/4: 选择路由策略{Colors.ENDC}")
        print(f"{'-'*60}\n")

        self.config['routing']['strategy'] = 'fallback'
        print("  首次配置默认采用 Fallback（故障转移）策略。")
        print("  如需更高级的策略，请在配置文件或后续 CLI 中调整。")
        print(f"\n{Colors.GREEN}✅ 路由策略：fallback{Colors.ENDC}")
    
    def _generate_auth(self):
        """生成认证信息"""
        print(f"\n{Colors.BOLD}🔐 步骤 4/4: 生成认证信息{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        api_key = f"sk-{secrets.token_hex(16)}"
        self.config['auth']['api_keys'].append({
            'key': api_key,
            'name': 'Default Key',
            'created_at': datetime.now().isoformat()
        })
        
        print(f"{Colors.GREEN}✅ 已生成用户侧 API Key{Colors.ENDC}")
        print(f"\n连接信息：")
        print(f"  Base URL: http://localhost:{self.config['server']['port']}/v1")
        print(f"  API Key:  {Colors.YELLOW}{api_key}{Colors.ENDC}")
        
        # 保存 auth.yaml
        auth_path = self.config_dir / 'auth.yaml'
        with open(auth_path, 'w') as f:
            yaml.dump({'api_keys': self.config['auth']['api_keys']}, f, default_flow_style=False)
    
    def _save_and_start(self):
        """保存配置并启动服务"""
        print(f"\n{Colors.BOLD}📁 保存配置{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        config_path = self.config_dir / 'config.yaml'
        with open(config_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"✅ 配置已保存:")
        print(f"   {config_path}")
        print(f"   {self.env_path}")
        print(f"   {self.config_dir / 'auth.yaml'}\n")
        
        # 询问是否启动服务
        start = input("是否立即启动服务？[Y/n]: ").strip().lower()
        if start != 'n':
            self._start_service()
        
        self._finish()
    
    def _start_service(self):
        """启动服务（先停止旧进程）"""
        import subprocess, signal, os, time
        
        print(f"\n{Colors.CYAN}启动服务...{Colors.ENDC}")
        
        python_exe = sys.executable
        host = self.config['server'].get('host', '0.0.0.0')
        port = str(self.config['server'].get('port', get_default_port()))

        # 先停止占用同一端口的旧进程
        try:
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True, text=True
            )
            pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            for pid_str in pids:
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except (ValueError, ProcessLookupError):
                    pass
            if pids:
                time.sleep(1.5)
                print(f"{Colors.YELLOW}  已停止旧服务 (PID: {', '.join(pids)}){Colors.ENDC}")
        except Exception:
            pass

        try:
            log_file = open(self.config_dir / 'server.log', 'a')
            process = subprocess.Popen(
                [python_exe, '-m', 'uvicorn', 'bridge_server.runtime:app', '--app-dir', 'src', '--host', host, '--port', port],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=REPO_ROOT
            )
            log_file.close()
            
            print(f"{Colors.GREEN}✅ 服务已启动！{Colors.ENDC}")
            print(f"   PID: {process.pid}")
            print(f"   端口：{port}")
        except Exception as e:
            print(f"{Colors.YELLOW}⚠️  服务启动失败：{e}{Colors.ENDC}")
            print(f"   可以手动启动：python -m uvicorn bridge_server.runtime:app --app-dir src --host {host} --port {port}")
    
    def _finish(self):
        """完成"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.GREEN}🎉 配置完成！{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}\n")
        
        print(f"连接信息：")
        print(f"  Base URL: http://localhost:{self.config['server']['port']}/v1")
        print(f"  API Key:  {self.config['auth']['api_keys'][0]['key']}")
        print(f"\n测试连接：")
        print(f"  curl http://localhost:{self.config['server']['port']}/health")
        print(f"\n管理命令：")
        print(f"  bridge-server start   - 启动服务")
        print(f"  bridge-server stop    - 停止服务")
        print(f"  bridge-server status  - 查看状态")
        print(f"\n{Colors.GREEN}祝您使用愉快！{Colors.ENDC}\n")


def main():
    """主函数"""
    wizard = SetupWizard()
    wizard.run()


if __name__ == "__main__":
    main()
