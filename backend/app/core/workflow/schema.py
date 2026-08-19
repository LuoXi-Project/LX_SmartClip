"""工作流定义契约：dataclass ↔ JSON 同构、强校验器、安全 when 求值器。

定义与 JSON 完全同构是本模块的核心约束：内置工作流（builtin.py）与
用户 / Agent 通过 API 提交的自定义工作流共用同一份结构，引擎只认 JSON。
校验错误结构化返回（{field, message}），可直接指导 LLM 自修正。

when 条件不走 eval：模板 ${...} 先替换为字面量，再用 ast 白名单求值器
（仅常量 / 比较 / and / or / not / 括号），Agent 生成的定义无任意代码执行风险。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

PARAM_TYPES = ("text", "textarea", "number", "select", "multiselect", "switch")

_WORKFLOW_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_STEP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# 参数模板引用：${inputs.copy_text} / ${steps.ingest.video_ids}
REF_RE = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")
# JSON 风格字面量 → Python 字面量（仅裸词，供 when 表达式使用）
_JSON_LITERAL_RE = re.compile(r"\b(true|false|null)\b")
_JSON_LITERAL_MAP = {"true": "True", "false": "False", "null": "None"}


class WorkflowDefError(ValueError):
    """定义不合法（信息面向用户 / LLM，可直接展示）。"""


# ── when 安全求值器（ast 白名单）──────────────────────────────────────────

_COMPARE_OPS: tuple[type, ...] = (
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
)


def normalize_json_literals(expr: str) -> str:
    """把 JSON 风格字面量（true/false/null）规范为 Python 字面量。"""
    return _JSON_LITERAL_RE.sub(lambda m: _JSON_LITERAL_MAP[m.group(1)], expr)


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (bool, int, float, str, type(None))):
            return node.value
        raise WorkflowDefError(f"when 条件包含不支持的常量: {node.value!r}")
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [_eval_node(v) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _COMPARE_OPS):
                raise WorkflowDefError(f"when 条件包含不支持的比较运算: {type(op).__name__}")
            right = _eval_node(comparator)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.In):
                ok = left in right
            else:
                ok = left not in right
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt) for elt in node.elts]
    if isinstance(node, ast.Dict):
        return {
            (_eval_node(k) if k is not None else None): _eval_node(v)
            for k, v in zip(node.keys, node.values)
        }
    raise WorkflowDefError(
        f"when 条件包含不支持的语法: {type(node).__name__}（仅支持常量/比较/and/or/not/括号）"
    )


def safe_eval_when(expr: str) -> bool:
    """求值 when 表达式（先做 JSON 字面量规范化）；语法/类型错误抛 WorkflowDefError。

    输入应已是「模板替换后的纯字面量」表达式（见 context.eval_when）。
    """
    expr = normalize_json_literals(expr)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise WorkflowDefError(f"when 条件语法错误: {expr!r}") from exc
    return bool(_eval_node(tree.body))


def check_when_syntax(when: str) -> None:
    """校验 when 语法（模板用 None 占位），不实际求值。"""
    substituted = REF_RE.sub("None", when)
    substituted = normalize_json_literals(substituted)
    safe_eval_when(substituted)


# ── 定义结构 ──────────────────────────────────────────────────────────────

@dataclass
class ParamSpec:
    """工作流输入参数声明（前端表单自动生成 / Agent 参数收集依据）。"""

    name: str
    label: str
    type: str = "text"
    required: bool = False
    default: Any = None
    options: list[dict] | None = None   # select/multiselect: [{"value":..., "label":...}]
    placeholder: str = ""
    help: str = ""

    def to_json(self) -> dict:
        d = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "placeholder": self.placeholder,
            "help": self.help,
        }
        if self.options:
            d["options"] = self.options
        return d

    @classmethod
    def from_json(cls, d: dict) -> "ParamSpec":
        return cls(
            name=str(d.get("name") or ""),
            label=str(d.get("label") or d.get("name") or ""),
            type=str(d.get("type") or "text"),
            required=bool(d.get("required")),
            default=d.get("default"),
            options=list(d["options"]) if isinstance(d.get("options"), list) else None,
            placeholder=str(d.get("placeholder") or ""),
            help=str(d.get("help") or ""),
        )


@dataclass
class WorkflowStep:
    name: str
    title: str
    action: str
    params: dict = field(default_factory=dict)
    when: str | None = None            # 为假时跳过；支持 ${...} 模板与 JSON 字面量
    continue_on_error: bool = False
    retries: int = 0
    timeout_sec: int = 7200
    depends_on: list[str] = field(default_factory=list)   # 预留 DAG，v1 顺序执行

    def to_json(self) -> dict:
        d: dict = {
            "name": self.name,
            "title": self.title,
            "action": self.action,
            "params": self.params,
        }
        if self.when is not None:
            d["when"] = self.when
        if self.continue_on_error:
            d["continue_on_error"] = True
        if self.retries:
            d["retries"] = self.retries
        if self.timeout_sec != 7200:
            d["timeout_sec"] = self.timeout_sec
        if self.depends_on:
            d["depends_on"] = list(self.depends_on)
        return d

    @classmethod
    def from_json(cls, d: dict) -> "WorkflowStep":
        return cls(
            name=str(d.get("name") or ""),
            title=str(d.get("title") or d.get("name") or ""),
            action=str(d.get("action") or ""),
            params=dict(d.get("params") or {}),
            when=str(d["when"]) if d.get("when") is not None else None,
            continue_on_error=bool(d.get("continue_on_error")),
            retries=max(0, int(d.get("retries") or 0)),
            timeout_sec=max(30, int(d.get("timeout_sec") or 7200)),
            depends_on=[str(x) for x in (d.get("depends_on") or [])],
        )


@dataclass
class WorkflowDef:
    id: str
    name: str
    description: str = ""
    category: str = "通用"
    params: list[ParamSpec] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    is_builtin: bool = False

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "is_builtin": self.is_builtin,
            "params": [p.to_json() for p in self.params],
            "steps": [s.to_json() for s in self.steps],
        }

    @classmethod
    def from_json(cls, d: dict) -> "WorkflowDef":
        return cls(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or d.get("id") or ""),
            description=str(d.get("description") or ""),
            category=str(d.get("category") or "通用"),
            params=[ParamSpec.from_json(p) for p in (d.get("params") or [])],
            steps=[WorkflowStep.from_json(s) for s in (d.get("steps") or [])],
            is_builtin=bool(d.get("is_builtin")),
        )

    def param_names(self) -> set[str]:
        return {p.name for p in self.params}


# ── 校验器 ────────────────────────────────────────────────────────────────

def _iter_refs(value: Any):
    """递归提取 params/when 中出现的全部 ${path} 引用。"""
    if isinstance(value, str):
        yield from REF_RE.findall(value)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_refs(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_refs(v)


def validate_workflow_def(data: Any) -> tuple[list[dict], WorkflowDef | None]:
    """强校验工作流定义。返回 (errors, 解析后的定义)。

    errors 为结构化列表 [{"field": ..., "message": ...}]，供前端/LLM 定位修正。
    """
    errors: list[dict] = []

    def err(field_name: str, message: str) -> None:
        errors.append({"field": field_name, "message": message})

    if not isinstance(data, dict):
        return [{"field": "", "message": "工作流定义必须是 JSON 对象"}], None

    wid = data.get("id")
    if not isinstance(wid, str) or not _WORKFLOW_ID_RE.match(wid):
        err("id", "id 必填，格式为小写字母开头的 snake_case（2~64 位，如 collect_to_render）")
    name = str(data.get("name") or "").strip()
    if not name:
        err("name", "name 必填（工作流显示名）")

    # params
    param_names: set[str] = set()
    raw_params = data.get("params") or []
    if not isinstance(raw_params, list):
        err("params", "params 必须是数组")
        raw_params = []
    for idx, p in enumerate(raw_params):
        if not isinstance(p, dict):
            err(f"params[{idx}]", "参数必须是对象")
            continue
        pname = str(p.get("name") or "")
        if not _STEP_NAME_RE.match(pname):
            err(f"params[{idx}].name", f"参数名 {pname!r} 不合法（小写字母开头的 snake_case）")
            continue
        if pname in param_names:
            err(f"params[{idx}].name", f"参数名 {pname!r} 重复")
        param_names.add(pname)
        ptype = str(p.get("type") or "text")
        if ptype not in PARAM_TYPES:
            err(f"params[{idx}].type", f"参数 {pname} 类型 {ptype!r} 不支持（可选: {', '.join(PARAM_TYPES)}）")
        if ptype in ("select", "multiselect") and not (isinstance(p.get("options"), list) and p["options"]):
            err(f"params[{idx}].options", f"参数 {pname} 为 {ptype} 类型，必须提供非空 options 数组")

    # steps
    raw_steps = data.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        err("steps", "steps 必须是非空数组（至少一个步骤）")
        raw_steps = []

    from .actions import ACTIONS, ensure_actions_loaded  # 延迟导入避免循环依赖

    ensure_actions_loaded()
    step_names: set[str] = set()
    for idx, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            err(f"steps[{idx}]", "步骤必须是对象")
            continue
        sname = str(s.get("name") or "")
        if not _STEP_NAME_RE.match(sname):
            err(f"steps[{idx}].name", f"步骤名 {sname!r} 不合法（小写字母开头的 snake_case）")
            continue
        if sname in step_names:
            err(f"steps[{idx}].name", f"步骤名 {sname!r} 重复")
        step_names.add(sname)
        action_name = str(s.get("action") or "")
        if action_name not in ACTIONS:
            available = ", ".join(sorted(ACTIONS))
            err(f"steps[{idx}].action", f"未知动作 {action_name!r}（可用动作: {available}）")
            continue
        # 模板引用检查：inputs 必须声明；steps 只能引用更早的步骤
        for ref in _iter_refs(s.get("params") or {}):
            parts = ref.split(".")
            root, rest = parts[0], parts[1:]
            if root == "inputs":
                if not rest or rest[0] not in param_names:
                    err(
                        f"steps[{idx}].params",
                        f"模板 ${{{ref}}} 引用了未声明的输入参数（可用: {sorted(param_names) or '无'}）",
                    )
            elif root == "steps":
                if not rest or rest[0] not in step_names:
                    err(
                        f"steps[{idx}].params",
                        f"模板 ${{{ref}}} 引用了不存在的步骤（已声明: {sorted(step_names)}）",
                    )
                elif rest[0] == sname:
                    err(f"steps[{idx}].params", f"模板 ${{{ref}}} 不能引用步骤自身的输出")
            else:
                err(f"steps[{idx}].params", f"模板 ${{{ref}}} 根必须是 inputs 或 steps")
        when = s.get("when")
        if isinstance(when, str) and when.strip():
            for ref in REF_RE.findall(when):
                root = ref.split(".")[0]
                if root not in ("inputs", "steps"):
                    err(f"steps[{idx}].when", f"模板 ${{{ref}}} 根必须是 inputs 或 steps")
            try:
                check_when_syntax(when)
            except WorkflowDefError as exc:
                err(f"steps[{idx}].when", str(exc))
        # depends_on 只能引用更早步骤（预留 DAG；v1 顺序执行）
        for dep in s.get("depends_on") or []:
            if dep not in step_names:
                err(f"steps[{idx}].depends_on", f"依赖 {dep!r} 不存在或不在本步骤之前")

    if errors:
        return errors, None
    return [], WorkflowDef.from_json(data)


def resolve_run_inputs(defn: WorkflowDef, raw: dict) -> tuple[list[dict], dict]:
    """合并默认值并按参数类型校验/收敛运行输入。返回 (errors, inputs)。"""
    errors: list[dict] = []
    if not isinstance(raw, dict):
        return [{"field": "inputs", "message": "inputs 必须是 JSON 对象"}], {}
    inputs: dict = {}
    raw_map = {str(k): v for k, v in raw.items()}
    known = defn.param_names()
    for extra in sorted(set(raw_map) - known):
        errors.append({"field": f"inputs.{extra}", "message": f"未知输入参数 {extra!r}（可用: {sorted(known)}）"})
    for spec in defn.params:
        value = raw_map.get(spec.name, spec.default)
        # 空值（未提供 / 空串）回退默认值；仍为空且必填 → 报错
        if value is None or (isinstance(value, str) and not value.strip()):
            value = spec.default if not spec.required else None
            if value is None or (isinstance(value, str) and not value.strip()):
                if spec.required:
                    errors.append({"field": f"inputs.{spec.name}", "message": f"参数「{spec.label}」必填"})
                inputs[spec.name] = None
                continue
        coerced, coerce_err = _coerce_param(spec, value)
        if coerce_err:
            errors.append({"field": f"inputs.{spec.name}", "message": coerce_err})
            continue
        inputs[spec.name] = coerced
    return errors, inputs


def _coerce_param(spec: ParamSpec, value: Any) -> tuple[Any, str | None]:
    """按参数类型宽松收敛（number 接受数字串；switch 接受 bool/true/false 串）。"""
    if spec.type == "number":
        try:
            return (float(value) if "." in str(value) else int(value)), None
        except (TypeError, ValueError):
            return None, f"参数「{spec.label}」需要数字"
    if spec.type == "switch":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
            return value.strip().lower() in ("true", "1"), None
        return None, f"参数「{spec.label}」需要布尔值"
    if spec.type == "select":
        sval = str(value)
        allowed = {str(o.get("value")) for o in (spec.options or [])}
        if allowed and sval not in allowed:
            return None, f"参数「{spec.label}」取值 {sval!r} 不在可选范围内"
        return sval, None
    if spec.type == "multiselect":
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        if not isinstance(value, list) or not all(isinstance(v, (str, int, float)) for v in value):
            return None, f"参数「{spec.label}」需要字符串数组"
        vals = [str(v) for v in value]
        allowed = {str(o.get("value")) for o in (spec.options or [])}
        bad = [v for v in vals if allowed and v not in allowed]
        if bad:
            return None, f"参数「{spec.label}」包含不可选值: {', '.join(bad)}"
        return vals, None
    return str(value), None
