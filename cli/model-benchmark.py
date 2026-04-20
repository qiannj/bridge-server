#!/usr/bin/env python3
"""
Bridge Server 模型能力摸底测试工具

对所有已配置的模型跑预定义题库，覆盖5个能力维度：
  - 代码编程    (coding)
  - 数学推理    (math)
  - 文学创作    (writing)
  - 语言翻译    (translation)
  - 日常对话    (chat)

输出能力矩阵，帮助用户为不同场景选择最合适的模型。
"""

import sys
import os
import json
import time
import yaml
import math
import re
import httpx
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# ── 路径配置 ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

if sys.platform == "win32":
    CONFIG_DIR = Path(os.environ.get("USERPROFILE", "")) / ".bridge-server"
else:
    CONFIG_DIR = Path.home() / ".bridge-server"

# ── 颜色 ─────────────────────────────────────────────────────────────────────
class C:
    CYAN   = "\033[96m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

# ── 题库 ─────────────────────────────────────────────────────────────────────
BENCHMARK_QUESTIONS: Dict[str, List[Dict]] = {
    "coding": [
        {
            "id": "code_1",
            "prompt": "用Python实现一个二分查找函数，要求：函数签名为 binary_search(arr, target)，包含详细注释，并给出时间复杂度。",
            "check": lambda r: bool(re.search(r"def binary_search", r) and ("O(" in r or "时间复杂度" in r)),
            "check_desc": "包含函数定义 + 复杂度说明",
        },
        {
            "id": "code_2",
            "prompt": "写一段JavaScript代码，使用Promise实现一个带超时控制的fetch请求（超时3秒自动拒绝），并加注释。",
            "check": lambda r: bool(re.search(r"Promise|fetch|timeout|setTimeout", r, re.I)),
            "check_desc": "包含 Promise/fetch/timeout 关键词",
        },
        {
            "id": "code_3",
            "prompt": "请找出以下Python代码中的bug并修复：\n```python\ndef find_max(lst):\n    max_val = lst[0]\n    for i in range(len(lst)):\n        if lst[i] > max_val:\n            max_val = lst[i+1]\n    return max_val\n```",
            "check": lambda r: bool(re.search(r"lst\[i\]|索引越界|index|bug|修复|错误", r, re.I)),
            "check_desc": "识别出索引越界bug",
        },
    ],
    "math": [
        {
            "id": "math_1",
            "prompt": "一列火车从A城出发，速度60km/h，同时另一列火车从B城出发，速度90km/h，两城相距600km，两车相向而行，请问几小时后相遇？给出完整解题过程。",
            "check": lambda r: bool(re.search(r"4\s*小时|4h|4\s*hour", r, re.I) or "4" in r),
            "check_desc": "答案包含 4（小时）",
        },
        {
            "id": "math_2",
            "prompt": "已知等差数列首项a₁=2，公差d=3，求第15项和前15项之和，请给出推导步骤。",
            "check": lambda r: bool(re.search(r"44|a_15|a15|第15项", r) and re.search(r"345|S_15|前15项之和", r)),
            "check_desc": "包含正确答案 a15=44，S15=345",
        },
        {
            "id": "math_3",
            "prompt": "用数学归纳法证明：对所有正整数n，1+2+3+...+n = n(n+1)/2",
            "check": lambda r: bool(re.search(r"归纳|induction|k\+1|假设|成立", r, re.I)),
            "check_desc": "包含归纳证明关键步骤",
        },
    ],
    "writing": [
        {
            "id": "write_1",
            "prompt": "以「第一场雪」为题，写一段200字左右的散文，要求意境优美，有具体的场景描写。",
            "check": lambda r: len(r) >= 100,
            "check_desc": "回复长度 ≥ 100 字",
        },
        {
            "id": "write_2",
            "prompt": "帮我写一封给领导申请居家办公的邮件，原因是家中有老人生病需要照料，语气正式但不失人情味，不超过150字。",
            "check": lambda r: bool(re.search(r"申请|敬请|居家|审批|办公|领导|尊敬", r)),
            "check_desc": "包含邮件正式用语",
        },
        {
            "id": "write_3",
            "prompt": "为一款主打「极简主义」风格的蓝牙耳机写一段产品介绍文案（80字以内），突出设计感和音质。",
            "check": lambda r: 20 <= len(r) <= 300,
            "check_desc": "长度适中（20-300字）",
        },
    ],
    "translation": [
        {
            "id": "trans_1",
            "prompt": '将以下古文翻译成现代英文：\n"知之者不如好之者，好之者不如乐之者。"（出自《论语》）\n请同时给出字面意思和引申义。',
            "check": lambda r: bool(re.search(r"know|learn|enjoy|love|delight|pleasure", r, re.I)),
            "check_desc": "英文包含 know/enjoy/love 等核心词",
        },
        {
            "id": "trans_2",
            "prompt": "将以下英文段落翻译成流畅的中文：\n\"Artificial intelligence is transforming every industry, from healthcare to finance, creating both unprecedented opportunities and significant challenges for society.\"",
            "check": lambda r: bool(re.search(r"人工智能|医疗|金融|机遇|挑战", r)),
            "check_desc": "包含核心词汇的中文翻译",
        },
        {
            "id": "trans_3",
            "prompt": "请将以下句子分别翻译成日语和法语：\n「春天来了，万物复苏。」",
            "check": lambda r: bool(re.search(r"春|春天|printemps|春が|haru", r, re.I)),
            "check_desc": "包含日语或法语的春天表达",
        },
    ],
    "chat": [
        {
            "id": "chat_1",
            "prompt": "我最近工作压力很大，经常失眠，有什么实用的放松建议？",
            "check": lambda r: len(r) >= 80 and bool(re.search(r"放松|呼吸|运动|睡眠|休息|建议", r)),
            "check_desc": "有实质性建议（≥80字）",
        },
        {
            "id": "chat_2",
            "prompt": "如果你是一种天气，你会是什么天气？为什么？（请给出有趣且有深度的回答）",
            "check": lambda r: len(r) >= 50,
            "check_desc": "有个性化回答（≥50字）",
        },
        {
            "id": "chat_3",
            "prompt": "我朋友说「人生苦短，及时行乐」，我觉得这句话有点问题，你怎么看？",
            "check": lambda r: bool(re.search(r"但|然而|不过|另一方面|平衡|责任|意义|价值", r)),
            "check_desc": "有辩证思考",
        },
    ],
}

DIMENSION_NAMES = {
    "coding":      "💻 代码编程",
    "math":        "🔢 数学推理",
    "writing":     "✍️  文学创作",
    "translation": "🌐 语言翻译",
    "chat":        "💬 日常对话",
}

# ── 配置加载 ──────────────────────────────────────────────────────────────────
def load_config() -> Dict:
    config_file = CONFIG_DIR / "config.yaml"
    if not config_file.exists():
        print(f"{C.RED}❌ 未找到配置文件：{config_file}{C.RESET}")
        print(f"   请先运行：python3 cli/setup-wizard.py")
        sys.exit(1)
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_env():
    env_file = CONFIG_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

def get_all_models(config: Dict) -> List[Tuple[str, str, str, str]]:
    """返回 [(provider_name, model_id, base_url, api_key), ...]"""
    results = []
    for p in config.get("providers", []):
        name = p.get("name", "unknown")
        base_url = p.get("base_url", "")
        env_key = p.get("api_key_env", "")
        api_key = os.environ.get(env_key, "")
        if not api_key:
            print(f"{C.YELLOW}⚠  跳过 {name}：环境变量 {env_key} 未设置{C.RESET}")
            continue
        for m in p.get("models", []):
            model_id = m.get("id") if isinstance(m, dict) else str(m)
            results.append((name, model_id, base_url, api_key))
    return results

# ── 单次请求 ──────────────────────────────────────────────────────────────────
def call_model(base_url: str, api_key: str, model_id: str, prompt: str,
               timeout: int = 90, max_tokens: int = 1000) -> Tuple[str, float, str]:
    """
    调用模型，返回 (content, latency_sec, error_msg)。
    """
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
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

# ── 评分逻辑 ──────────────────────────────────────────────────────────────────
def score_response(content: str, latency: float, check_fn, error: str) -> Dict:
    """
    综合评分（0-100）：
      - 内容质量检查  40分（通过/未通过）
      - 响应完整性    30分（长度是否合理）
      - 响应速度      30分（越快越高）
    """
    if error:
        return {"score": 0, "quality": False, "latency": latency, "error": error}

    quality = check_fn(content)
    q_score = 40 if quality else 0

    # 长度分（500字以上满分，少于20字得0分）
    length = len(content)
    l_score = min(30, int(length / 500 * 30)) if length >= 20 else 0

    # 速度分（10s以内满分，超过90s得0分）
    speed = max(0, 30 - int((latency - 5) / 85 * 30)) if latency > 5 else 30

    total = q_score + l_score + speed
    return {
        "score": total,
        "quality": quality,
        "latency": round(latency, 1),
        "length": length,
        "error": "",
    }

def stars(score: int) -> str:
    """将 0-100 分转为 ★☆ 显示"""
    s = round(score / 20)  # 0-5 stars
    return "★" * s + "☆" * (5 - s)

# ── 主逻辑 ────────────────────────────────────────────────────────────────────
def run_benchmark(models: List[Tuple], dimensions: List[str],
                  questions_per_dim: int) -> Dict:
    """
    跑摸底测试，返回结果字典。
    results[model_key][dimension] = {score, quality, latency, ...}
    """
    results: Dict[str, Dict] = {}

    total_calls = len(models) * len(dimensions) * questions_per_dim
    done = 0

    for provider, model_id, base_url, api_key in models:
        model_key = f"{provider}/{model_id}"
        results[model_key] = {}

        for dim in dimensions:
            questions = BENCHMARK_QUESTIONS[dim][:questions_per_dim]
            dim_scores = []

            for q in questions:
                done += 1
                pct = int(done / total_calls * 100)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"\r  [{bar}] {pct:3d}%  {model_key}  {DIMENSION_NAMES[dim]}  {q['id']}        ",
                      end="", flush=True)

                content, latency, error = call_model(base_url, api_key, model_id, q["prompt"])
                result = score_response(content, latency, q["check"], error)
                result["question_id"] = q["id"]
                result["content_preview"] = content[:200]
                dim_scores.append(result)

            # 该维度平均分
            avg_score = int(sum(r["score"] for r in dim_scores) / len(dim_scores)) if dim_scores else 0
            avg_latency = round(sum(r["latency"] for r in dim_scores) / len(dim_scores), 1)
            quality_rate = sum(1 for r in dim_scores if r["quality"]) / len(dim_scores) if dim_scores else 0

            results[model_key][dim] = {
                "score": avg_score,
                "stars": stars(avg_score),
                "quality_rate": round(quality_rate, 2),
                "avg_latency": avg_latency,
                "details": dim_scores,
            }

    print()  # 换行
    return results

def print_capability_matrix(results: Dict, dimensions: List[str]):
    """打印能力矩阵 ASCII 表格"""
    if not results:
        return

    dim_labels = [DIMENSION_NAMES[d] for d in dimensions]
    col_w = max(12, max(len(l) for l in dim_labels) + 2)
    model_col = max(20, max(len(k) for k in results.keys()) + 2)

    # 表头
    header = f"{'模型':<{model_col}}" + "".join(f"{l:^{col_w}}" for l in dim_labels) + f"{'综合':^10}"
    sep = "─" * (model_col + col_w * len(dimensions) + 10)

    print(f"\n{C.BOLD}{C.CYAN}{'='*len(sep)}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  📊 模型能力矩阵{C.RESET}")
    print(f"{C.CYAN}{'='*len(sep)}{C.RESET}\n")
    print(f"{C.BOLD}{header}{C.RESET}")
    print(sep)

    ranked = []
    for model_key, dim_results in results.items():
        scores = [dim_results.get(d, {}).get("score", 0) for d in dimensions]
        overall = int(sum(scores) / len(scores)) if scores else 0
        ranked.append((model_key, dim_results, scores, overall))
    ranked.sort(key=lambda x: -x[3])

    for model_key, dim_results, scores, overall in ranked:
        row = f"{model_key:<{model_col}}"
        for i, d in enumerate(dimensions):
            info = dim_results.get(d, {})
            s = info.get("stars", "─────")
            row += f"{s:^{col_w}}"
        color = C.GREEN if overall >= 70 else (C.YELLOW if overall >= 50 else C.RED)
        row += f"{color}{overall:^10}{C.RESET}"
        print(row)

    print(sep)

    # 详细数据
    print(f"\n{C.BOLD}详细得分（0-100）及平均响应时间：{C.RESET}")
    print(f"{'模型':<{model_col}}" + "".join(f"{'分/延迟(s)':^{col_w}}" for _ in dimensions))
    print("─" * (model_col + col_w * len(dimensions)))
    for model_key, dim_results, scores, overall in ranked:
        row = f"{model_key:<{model_col}}"
        for d in dimensions:
            info = dim_results.get(d, {})
            cell = f"{info.get('score',0):2d}分/{info.get('avg_latency',0):.1f}s"
            row += f"{cell:^{col_w}}"
        print(row)

def print_routing_suggestions(results: Dict, dimensions: List[str]):
    """根据能力矩阵给出路由建议"""
    if not results:
        return

    print(f"\n{C.BOLD}{C.CYAN}🎯 路由配置建议{C.RESET}")
    print("─" * 50)

    dim_to_scenario = {
        "coding":      ("coding",  "编程辅助"),
        "math":        ("complex", "复杂推理"),
        "writing":     ("writing", "写作创作"),
        "translation": ("translation", "翻译"),
        "chat":        ("chat",    "日常对话"),
    }

    for dim in dimensions:
        best_model = max(results.keys(),
                         key=lambda k: results[k].get(dim, {}).get("score", 0))
        best_score = results[best_model].get(dim, {}).get("score", 0)
        scenario_key, scenario_name = dim_to_scenario.get(dim, (dim, dim))
        color = C.GREEN if best_score >= 70 else C.YELLOW
        print(f"  {DIMENSION_NAMES[dim]:<16}  → {color}{best_model}{C.RESET}  ({best_score}分)")

    print(f"\n  将以上建议填入 setup wizard 的场景化模型配置中即可。")

def save_results(results: Dict, dimensions: List[str]):
    out_file = CONFIG_DIR / "benchmark_results.yaml"
    data = {
        "generated_at": datetime.now().isoformat(),
        "dimensions": dimensions,
        "results": {}
    }
    for model_key, dim_results in results.items():
        data["results"][model_key] = {}
        for dim, info in dim_results.items():
            data["results"][model_key][dim] = {
                "score": info["score"],
                "stars": info["stars"],
                "quality_rate": info["quality_rate"],
                "avg_latency_sec": info["avg_latency"],
            }
    with open(out_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    print(f"\n{C.GREEN}✅ 结果已保存：{out_file}{C.RESET}")

# ── 入口 ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{C.CYAN}{'='*60}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  Bridge Server 模型能力摸底测试工具{C.RESET}")
    print(f"{C.CYAN}{'='*60}{C.RESET}")
    print(f"""
本工具将使用您配置的 API Key，对所有已配置的模型跑一套
预定义题库，涵盖以下5个能力维度：

  💻 代码编程  ─ 代码生成、Bug排查、算法实现
  🔢 数学推理  ─ 应用题、数列、数学归纳法
  ✍️  文学创作  ─ 散文写作、邮件、文案
  🌐 语言翻译  ─ 中英互译、古文、多语种
  💬 日常对话  ─ 情感支持、开放性问题、辩证思考

每个维度 {C.BOLD}3道题{C.RESET}，每题消耗约 500-1000 tokens。
测试完成后输出能力矩阵 + 路由配置建议。
""")

    load_env()
    config = load_config()
    models = get_all_models(config)

    if not models:
        print(f"{C.RED}❌ 没有可用的模型，请检查配置和环境变量{C.RESET}")
        sys.exit(1)

    print(f"{C.BOLD}已发现 {len(models)} 个可测试模型：{C.RESET}")
    for provider, model_id, _, _ in models:
        print(f"  • {provider}/{model_id}")

    # 选择维度
    all_dims = list(BENCHMARK_QUESTIONS.keys())
    print(f"\n{C.BOLD}测试维度（默认全选）：{C.RESET}")
    for i, d in enumerate(all_dims, 1):
        print(f"  {i}. {DIMENSION_NAMES[d]}")
    dim_input = input("\n请输入维度编号（逗号分隔，回车=全选）: ").strip()
    if dim_input:
        indices = [int(x.strip()) - 1 for x in dim_input.split(",") if x.strip().isdigit()]
        dimensions = [all_dims[i] for i in indices if 0 <= i < len(all_dims)]
        if not dimensions:
            dimensions = all_dims
    else:
        dimensions = all_dims

    questions_per_dim = 3
    total_calls = len(models) * len(dimensions) * questions_per_dim
    est_tokens = total_calls * 750
    est_cost_hint = f"约 {est_tokens:,} tokens（实际费用取决于各平台定价）"

    print(f"\n{C.YELLOW}⚠️  测试将发起 {total_calls} 次 API 调用，{est_cost_hint}{C.RESET}")
    confirm = input("确认开始测试？[y/N]: ").strip().lower()
    if confirm != "y":
        print("已取消。")
        sys.exit(0)

    print(f"\n{C.BOLD}开始测试...（这可能需要几分钟）{C.RESET}\n")
    t_start = time.perf_counter()

    results = run_benchmark(models, dimensions, questions_per_dim)

    elapsed = time.perf_counter() - t_start
    print(f"\n{C.GREEN}✅ 测试完成，耗时 {elapsed:.1f}s{C.RESET}")

    print_capability_matrix(results, dimensions)
    print_routing_suggestions(results, dimensions)
    save_results(results, dimensions)


if __name__ == "__main__":
    main()
