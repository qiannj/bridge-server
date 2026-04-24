"""
ExpressionRouter — 安全表达式路由引擎 (Layer 2)
===============================================
允许管理员通过 YAML 配置中的简单表达式定义路由规则，
无需编写 Python 代码，消除代码注入风险。

配置示例（config.yaml）：
  expression_router:
    enabled: true
    rules:
      - expr: "len(message) > 3000 and contains(message, '分析')"
        model: "moonshot/kimi-chat"
        reason: "长文分析任务"
      - expr: "hour() >= 22 or hour() < 8"
        model: "dashscope/qwen3.5-flash"
        reason: "夜间低成本模型"
      - expr: "match(message, r'代码|编程|函数|debug|bug')"
        model: "openai/gpt-4o"
        reason: "编程任务"

安全保证：
  - 不调用 Python 内置 eval()
  - 通过 AST 白名单验证所有表达式节点类型
  - 只允许白名单函数：len/contains/match/starts_with/ends_with/hour/weekday
  - 输入数据仅来自只读 context 对象
  - 无文件系统访问，无网络访问，无 import
"""
from __future__ import annotations

import ast
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 白名单：允许的 AST 节点类型 ────────────────────────────────────────────────

_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp,     # and / or
    ast.UnaryOp,    # not
    ast.Compare,    # >, <, >=, <=, ==, !=
    ast.BinOp,      # +, -, *, /（用于数字计算）
    ast.Call,       # 白名单函数调用
    ast.Constant,   # 字符串、数字、布尔字面量
    ast.Name,       # 变量名（只允许 True/False/None）
    ast.And,
    ast.Or,
    ast.Not,
    ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.In, ast.NotIn,
    ast.List,       # 列表字面量（用于 in 运算）
    ast.Tuple,
    ast.IfExp,      # 三元表达式 a if c else b
    ast.Load,       # Name/List/Tuple 节点的上下文（只读）
    ast.Store,      # AST 内部需要，实际表达式中不会出现写操作
    ast.Del,
    # ast.Attribute 故意不包含，防止对象属性访问
)

# 白名单函数：名称 -> 实现
# 所有函数均为纯函数，不接受外部副作用
_WHITELIST_FUNCTIONS = {
    "len",
    "contains",
    "starts_with",
    "ends_with",
    "match",       # 正则匹配
    "hour",        # 当前小时（0-23）
    "weekday",     # 当前星期（0=周一 … 6=周日）
    "lower",       # 转小写
    "upper",       # 转大写
    "strip",       # 去首尾空白
    "min",
    "max",
    "abs",
    "int",
    "float",
    "str",
    "bool",
}

# 允许作为 Name 节点的变量名
_ALLOWED_NAMES = {"True", "False", "None", "message"}


# ── 表达式验证 ─────────────────────────────────────────────────────────────────

def _validate_expr_ast(tree: ast.AST, expr_str: str) -> Optional[str]:
    """
    遍历表达式 AST，检查所有节点是否在白名单内。
    返回 None 表示通过，返回字符串表示错误原因。
    """
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            return (
                f"表达式含有不允许的操作: {type(node).__name__}。"
                f"仅允许基础比较/逻辑运算和白名单函数。"
            )
        if isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Name):
                return "不允许调用方法（obj.method()），只允许调用顶层函数"
            if func.id not in _WHITELIST_FUNCTIONS:
                return (
                    f"函数 '{func.id}' 不在白名单中。"
                    f"允许的函数: {sorted(_WHITELIST_FUNCTIONS)}"
                )
        if isinstance(node, ast.Name):
            if node.id not in _ALLOWED_NAMES and node.id not in _WHITELIST_FUNCTIONS:
                return (
                    f"变量名 '{node.id}' 不允许。"
                    f"只允许: {sorted(_ALLOWED_NAMES)}"
                )
    return None


def validate_expression(expr_str: str) -> Optional[str]:
    """
    验证表达式字符串语法和安全性。
    返回 None 表示合法，返回字符串表示错误原因。
    """
    try:
        tree = ast.parse(expr_str.strip(), mode="eval")
    except SyntaxError as e:
        return f"语法错误: {e}"
    return _validate_expr_ast(tree, expr_str)


# ── 表达式求值 ─────────────────────────────────────────────────────────────────

def _safe_eval_node(node: ast.AST, env: Dict[str, Any]) -> Any:
    """手动求值 AST 节点，不使用 Python 内置 eval()。"""

    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body, env)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        name = node.id
        if name == "True":
            return True
        if name == "False":
            return False
        if name == "None":
            return None
        if name in env:
            return env[name]
        raise ValueError(f"未定义的变量: '{name}'")

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for v in node.values:
                result = _safe_eval_node(v, env)
                if not result:
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for v in node.values:
                result = _safe_eval_node(v, env)
                if result:
                    return True
            return False

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _safe_eval_node(node.operand, env)

    if isinstance(node, ast.Compare):
        left = _safe_eval_node(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _safe_eval_node(comparator, env)
            if isinstance(op, ast.Gt):
                if not (left > right):
                    return False
            elif isinstance(op, ast.Lt):
                if not (left < right):
                    return False
            elif isinstance(op, ast.GtE):
                if not (left >= right):
                    return False
            elif isinstance(op, ast.LtE):
                if not (left <= right):
                    return False
            elif isinstance(op, ast.Eq):
                if not (left == right):
                    return False
            elif isinstance(op, ast.NotEq):
                if not (left != right):
                    return False
            elif isinstance(op, ast.In):
                if left not in right:
                    return False
            elif isinstance(op, ast.NotIn):
                if left in right:
                    return False
            left = right
        return True

    if isinstance(node, ast.BinOp):
        left = _safe_eval_node(node.left, env)
        right = _safe_eval_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError(f"不支持的二元运算: {type(node.op).__name__}")

    if isinstance(node, ast.IfExp):
        cond = _safe_eval_node(node.test, env)
        return _safe_eval_node(node.body if cond else node.orelse, env)

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_safe_eval_node(elt, env) for elt in node.elts]

    if isinstance(node, ast.Call):
        func_name = node.func.id  # type: ignore[union-attr]
        args = [_safe_eval_node(a, env) for a in node.args]
        return _dispatch_function(func_name, args)

    raise ValueError(f"不支持的 AST 节点类型: {type(node).__name__}")


def _dispatch_function(name: str, args: list) -> Any:
    """执行白名单函数。"""
    if name == "len":
        return len(args[0]) if args else 0
    if name == "contains":
        s, sub = str(args[0]) if args else "", str(args[1]) if len(args) > 1 else ""
        return sub in s
    if name == "starts_with":
        s, prefix = str(args[0]) if args else "", str(args[1]) if len(args) > 1 else ""
        return s.startswith(prefix)
    if name == "ends_with":
        s, suffix = str(args[0]) if args else "", str(args[1]) if len(args) > 1 else ""
        return s.endswith(suffix)
    if name == "match":
        pattern = str(args[1]) if len(args) > 1 else ""
        text = str(args[0]) if args else ""
        try:
            return bool(re.search(pattern, text, re.IGNORECASE))
        except re.error:
            return False
    if name == "hour":
        return datetime.now().hour
    if name == "weekday":
        return datetime.now().weekday()
    if name == "lower":
        return str(args[0]).lower() if args else ""
    if name == "upper":
        return str(args[0]).upper() if args else ""
    if name == "strip":
        return str(args[0]).strip() if args else ""
    if name == "min":
        return min(*args) if len(args) > 1 else (min(args[0]) if args else 0)
    if name == "max":
        return max(*args) if len(args) > 1 else (max(args[0]) if args else 0)
    if name == "abs":
        return abs(args[0]) if args else 0
    if name == "int":
        return int(args[0]) if args else 0
    if name == "float":
        return float(args[0]) if args else 0.0
    if name == "str":
        return str(args[0]) if args else ""
    if name == "bool":
        return bool(args[0]) if args else False
    raise ValueError(f"未知函数: '{name}'")


def eval_expression(expr_str: str, message: str) -> bool:
    """
    对给定的消息文本求值表达式。
    若表达式出错返回 False（静默降级）。
    """
    try:
        tree = ast.parse(expr_str.strip(), mode="eval")
        env = {"message": message}
        result = _safe_eval_node(tree, env)
        return bool(result)
    except Exception as e:
        logger.debug(f"表达式求值失败 [{expr_str!r}]: {e}")
        return False


# ── 主类 ──────────────────────────────────────────────────────────────────────

class ExpressionRule:
    """单条表达式路由规则。"""

    def __init__(self, data: Dict[str, Any]):
        self.expr: str = str(data.get("expr", ""))
        self.model: str = str(data.get("model", ""))
        self.reason: str = str(data.get("reason", "表达式路由"))
        self.priority: int = int(data.get("priority", 0))
        self._valid: bool = False
        self._error: Optional[str] = None

        err = validate_expression(self.expr)
        if err:
            self._error = err
            logger.warning(f"表达式规则验证失败 [{self.expr!r}]: {err}")
        else:
            self._valid = True

    @property
    def is_valid(self) -> bool:
        return self._valid and bool(self.expr) and bool(self.model)

    def matches(self, message: str) -> bool:
        if not self.is_valid:
            return False
        return eval_expression(self.expr, message)


class ExpressionRouter:
    """
    表达式路由器（Layer 2）。
    按 priority 降序逐条匹配规则，返回第一个匹配的模型。
    """

    def __init__(self, config: Dict[str, Any]):
        self.enabled: bool = bool(config.get("enabled", False))
        self._rules: List[ExpressionRule] = []
        self._load_rules(config.get("rules", []))

    def reload(self, config: Dict[str, Any]) -> None:
        self.enabled = bool(config.get("enabled", False))
        self._load_rules(config.get("rules", []))

    def _load_rules(self, rules_data: List[Dict[str, Any]]) -> None:
        rules = [ExpressionRule(r) for r in (rules_data or [])]
        self._rules = sorted(
            [r for r in rules if r.is_valid],
            key=lambda r: r.priority,
            reverse=True,
        )
        invalid = [r for r in rules if not r.is_valid]
        if invalid:
            logger.warning(f"ExpressionRouter: {len(invalid)} 条规则验证失败，已跳过")
        logger.info(f"ExpressionRouter 加载完成: {len(self._rules)} 条有效规则")

    def route(self, message: str) -> Optional[Tuple[str, str, str]]:
        """
        对消息进行表达式路由匹配。

        Returns:
            (provider_id, model_id, reason) 若匹配成功
            None 若无规则匹配
        """
        if not self.enabled or not self._rules:
            return None

        for rule in self._rules:
            try:
                if rule.matches(message):
                    provider_id, model_id = _parse_model(rule.model)
                    if provider_id and model_id:
                        logger.debug(
                            f"表达式路由命中: {rule.model} | 规则: {rule.expr!r} | 原因: {rule.reason}"
                        )
                        return provider_id, model_id, rule.reason
            except Exception as e:
                logger.warning(f"表达式规则执行异常 [{rule.expr!r}]: {e}")

        return None

    def get_rules_info(self) -> List[Dict[str, Any]]:
        """返回所有规则的摘要信息（用于 Admin API 展示）。"""
        return [
            {
                "expr": r.expr,
                "model": r.model,
                "reason": r.reason,
                "priority": r.priority,
                "valid": r.is_valid,
            }
            for r in self._rules
        ]


def _parse_model(model_str: str) -> Tuple[str, str]:
    """解析 'provider/model' 字符串。"""
    if not model_str:
        return "", ""
    idx = model_str.find("/")
    if idx == -1:
        return model_str, model_str
    return model_str[:idx], model_str[idx + 1:]


# ── 全局单例 ───────────────────────────────────────────────────────────────────

_expression_router: Optional[ExpressionRouter] = None


def get_expression_router() -> Optional[ExpressionRouter]:
    return _expression_router


def set_expression_router(instance: Optional[ExpressionRouter]) -> None:
    global _expression_router
    _expression_router = instance
