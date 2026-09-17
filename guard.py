"""回复校验与确定性降级。不调用模型。"""

from __future__ import annotations

import json
import re
from typing import Any

import params
from contract import Assessment
from state import get_playbook

# G3 整词/整句违禁，不做单字匹配。
_BANNED = (
    "治愈",
    "痊愈",
    "恢复正常",
    "可以停药",
    "你患有",
    "中风",
    "心梗",
    "可能导致",
    "剂量",
    "你应该",
    "你必须",
    "不配合",
    "不听话",
)

# G4b：升级动作代码 → 行动层必须出现的完整表述（不用“医”单字）。
_ESCALATION_PHRASE = {
    "contact_doctor": "联系医生",
    "seek_professional_help": "尽快就医",
}

# G2 允许出现的通用参考线，不是个体化目标。
_GENERIC_THRESHOLDS = {140.0, 90.0}

# 日期 / 天数 / 序号 / 次数 / 流程性单位：这些数字不参与事实校验。
_PROCESS_UNITS = ("天", "次", "条", "年", "月", "日", "号", "周")

_NUMBER_RE = re.compile(
    r"(?P<seq>第)?"
    r"(?P<num>-?\d+(?:\.\d+)?)"
    r"(?:\s*(?P<unit>%|％|天|次|条|年|月|日|号|周))?"
)
_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_SENTENCE_RE = re.compile(r"[。！？!?；;]+")
_ACTION_SPLIT_RE = re.compile(r"[。；;]+")


def _as_text(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple)):
            chunks.append(" ".join(str(item) for item in part))
        else:
            chunks.append(str(part))
    return " ".join(chunks)


def _reply_blob(reply: dict) -> str:
    return _as_text(
        reply.get("fact"),
        reply.get("explain"),
        reply.get("action"),
        reply.get("escalation_action"),
        reply.get("disclaimers"),
    )


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _expand_allowed(values: set[float]) -> set[float]:
    """把 fact_values 扩成文案里常见的圆整/百分数写法。"""
    allowed = set(_GENERIC_THRESHOLDS)
    for raw in values:
        value = float(raw)
        allowed.add(value)
        for digits in (0, 1, 2):
            allowed.add(float(round(value, digits)))
        allowed.add(float(int(value)))
        if abs(value) <= 1:
            percent = value * 100
            allowed.add(percent)
            allowed.add(float(round(percent)))
            allowed.add(float(round(percent, 1)))
            allowed.add(float(int(percent)))
        if value < 0:
            allowed.add(abs(value))
            allowed.add(float(round(abs(value))))
            allowed.add(float(round(abs(value), 1)))
    return allowed


def _close_to_allowed(number: float, allowed: set[float]) -> bool:
    for item in allowed:
        if abs(number - item) < 0.051:
            return True
    return False


def _extract_fact_numbers(text: str) -> list[float]:
    """抽取血压、心率、百分比、变化幅度；跳过日期/天数/序号/次数。"""
    cleaned = _DATE_RE.sub(" ", text)
    found: list[float] = []
    for match in _NUMBER_RE.finditer(cleaned):
        if match.group("seq"):
            continue
        unit = match.group("unit") or ""
        if unit in _PROCESS_UNITS:
            continue
        number = float(match.group("num"))
        if unit in ("%", "％"):
            found.append(number)
            found.append(number / 100.0)
            continue
        found.append(number)
    return found


def _mentions_number(text: str, value: float | None) -> bool:
    if value is None:
        return False
    allowed = _expand_allowed({float(value)})
    return any(_close_to_allowed(number, allowed) for number in _extract_fact_numbers(text))


def _must_do_needles(item: str, assessment: Assessment) -> list[str]:
    """从策略卡 must_do 抽出应答里应出现的表述；升级动作交给 G4b。"""
    text = item.strip()
    if "contact_doctor" in text or "seek_professional_help" in text:
        return []
    quoted = re.findall(r"「([^」]+)」", text)
    if quoted:
        return quoted
    if "：" in text:
        tail = text.split("：", 1)[1].strip()
        if "测一次" in tail:
            return ["测一次"]
        if tail:
            return [tail]
    parens = re.findall(r"（([^）]+)）", text)
    chinese = [part for part in parens if re.search(r"[\u4e00-\u9fff]", part)]
    if chinese:
        return chinese
    specials = {
        "说明是哪次读数触发": ["读数"],
        "提示规范复测确认": ["复测"],
        "建议记录并在复诊时提出": ["记录", "复诊"],
        "建议连续记录并带给医生": ["记录"],
        "强调不自行调整用药": ["用药"],
        "说明晨晚差异的具体数值": [],
        "给出近7天均值和达标比例": [],
        "说明近14天 vs 前14天的下降幅度": [],
        "把变化归到「坚持测量和生活方式」的过程上": ["坚持"],
        "提醒继续观察、不停药": ["观察"],
        "确认当前状态": [],
        "给一个维持动作": [],
    }
    return specials.get(text, [])


def _check_must_do_item(item: str, blob: str, assessment: Assessment) -> str | None:
    if "均值" in item and "达标" in item:
        mean = assessment.bp.get("sys_mean_7d")
        rate = assessment.bp.get("target_rate_30d")
        if not _mentions_number(blob, mean) or not _mentions_number(blob, rate):
            return f"G4a 未给出近7天均值和达标比例：{item}"
        return None
    if "晨晚差异" in item:
        morning = assessment.pattern.get("morning_mean")
        evening = assessment.pattern.get("evening_mean")
        delta = assessment.pattern.get("delta")
        if not (
            _mentions_number(blob, morning)
            and _mentions_number(blob, evening)
            or _mentions_number(blob, delta)
        ):
            return f"G4a 未说明晨晚差异数值：{item}"
        return None
    if "下降幅度" in item or "近14天" in item:
        compare = assessment.trend.get("compare_14d")
        if not _mentions_number(blob, compare):
            return f"G4a 未说明近14天对比幅度：{item}"
        return None
    for needle in _must_do_needles(item, assessment):
        if needle and needle not in blob:
            return f"G4a 缺少必带表述「{needle}」：{item}"
    return None


def _g1_structure(reply: dict) -> list[str]:
    # G1 JSON 结构完整：fact / explain / action 都必须是非空字符串。
    reasons = []
    if not isinstance(reply, dict):
        return ["G1 JSON 结构不完整"]
    for key in ("fact", "explain", "action"):
        if not _nonempty_str(reply.get(key)):
            reasons.append(f"G1 缺少非空字段 {key}")
    return reasons


def _g2_facts(reply: dict, assessment: Assessment) -> list[str]:
    # G2 事实值校验：只核对血压/心率/百分比/变化幅度，禁止编造。
    allowed = _expand_allowed(assessment.fact_values())
    blob = _as_text(reply.get("fact"), reply.get("explain"), reply.get("action"))
    reasons = []
    for number in _extract_fact_numbers(blob):
        if _close_to_allowed(number, allowed):
            continue
        reasons.append(f"G2 出现未登记的事实数值 {number}")
    return reasons


def _g3_banned(reply: dict) -> list[str]:
    # G3 违禁词：诊断承诺、预后恐吓、个体化用药、羞耻化措辞。
    blob = _reply_blob(reply)
    reasons = []
    for word in _BANNED:
        if word in blob:
            reasons.append(f"G3 含违禁词「{word}」")
    return reasons


def _g4a_strategy(reply: dict, assessment: Assessment) -> list[str]:
    # G4a 状态一致性：数据不足必须声明；其余按当前 Playbook.must_do 逐项检查。
    blob = _reply_blob(reply)
    if assessment.sufficient is False:
        if "数据不足" not in blob:
            return ["G4a 数据不足时未声明「数据不足」"]
        return []
    if not assessment.state:
        return ["G4a 缺少最终 state，无法核对策略卡"]
    playbook = get_playbook(assessment.state)
    reasons = []
    for item in playbook.get("must_do") or []:
        missed = _check_must_do_item(item, blob, assessment)
        if missed:
            reasons.append(missed)
    return reasons


def _g4b_escalation(reply: dict, assessment: Assessment) -> list[str]:
    # G4b 升级动作校验：字段值必须等于判读结果，行动层必须含对应完整表述。
    if not assessment.escalation_required:
        return []
    expected = assessment.escalation_action
    actual = reply.get("escalation_action")
    reasons = []
    if actual != expected:
        reasons.append("G4b escalation_action 与判读结果不一致")
    phrase = _ESCALATION_PHRASE.get(expected or "")
    action = str(reply.get("action") or "")
    if phrase and phrase not in action:
        reasons.append(f"G4b action 未含对应升级表述「{phrase}」")
    return reasons


def _g5_single_action(reply: dict) -> list[str]:
    # G5 action 单一：按句号/分号切开后最多两段，避免一次塞多个任务。
    action = str(reply.get("action") or "").strip()
    parts = [part.strip() for part in _ACTION_SPLIT_RE.split(action) if part.strip()]
    if len(parts) > 2:
        return [f"G5 action 分段过多（{len(parts)} > 2）"]
    return []


def _g6_length(reply: dict) -> list[str]:
    # G6 长度：fact+explain+action 总字数、以及各字段单句，都读 params.TEXT。
    fields = [str(reply.get(key) or "") for key in ("fact", "explain", "action")]
    total = sum(len(text.replace(" ", "")) for text in fields)
    reasons = []
    if total > params.TEXT.max_total_chars:
        reasons.append(f"G6 总字数 {total} > {params.TEXT.max_total_chars}")
    for text in fields:
        compact = text.replace(" ", "")
        sentences = [part.strip() for part in _SENTENCE_RE.split(compact) if part.strip()]
        if not sentences and compact:
            sentences = [compact]
        for piece in sentences:
            if len(piece) > params.TEXT.max_sentence_chars:
                reasons.append(
                    f"G6 单句字数 {len(piece)} > {params.TEXT.max_sentence_chars}"
                )
    return reasons


def validate(reply: dict, assessment: Assessment) -> tuple[bool, list[str]]:
    """依次跑 G1–G6。ok=全部通过；reasons=未通过项。"""
    reasons: list[str] = []
    reasons.extend(_g1_structure(reply))
    if reasons:
        return False, reasons
    reasons.extend(_g2_facts(reply, assessment))
    reasons.extend(_g3_banned(reply))
    reasons.extend(_g4a_strategy(reply, assessment))
    reasons.extend(_g4b_escalation(reply, assessment))
    reasons.extend(_g5_single_action(reply))
    reasons.extend(_g6_length(reply))
    return (not reasons), reasons


def inspect(reply: dict, assessment: Assessment) -> list[dict]:
    """Debug 用：逐项跑 G1–G6，不改变 validate 的短路逻辑。"""
    g1 = _g1_structure(reply)
    g2 = _g2_facts(reply, assessment)
    g3 = _g3_banned(reply)
    g4a = _g4a_strategy(reply, assessment)
    g4b = _g4b_escalation(reply, assessment)
    g5 = _g5_single_action(reply)
    g6 = _g6_length(reply)
    return [
        {"id": "G1", "name": "JSON 结构", "ok": not g1, "reasons": g1},
        {"id": "G2", "name": "事实值", "ok": not g2, "reasons": g2},
        {"id": "G3", "name": "违禁词", "ok": not g3, "reasons": g3},
        {"id": "G4a", "name": "策略一致", "ok": not g4a, "reasons": g4a},
        {
            "id": "G4b",
            "name": "升级动作",
            "ok": not g4b,
            "reasons": g4b,
            "expected": assessment.escalation_action,
            "actual": reply.get("escalation_action") if isinstance(reply, dict) else None,
            "escalation_required": bool(assessment.escalation_required),
        },
        {"id": "G5", "name": "单一行动", "ok": not g5, "reasons": g5},
        {"id": "G6", "name": "长度", "ok": not g6, "reasons": g6},
    ]


# 把 Playbook.must_do 落到行动层短句。说明类 must_do 放 fact，不在这里重复。
_MUST_DO_ACTION = {
    "提示规范复测确认": "先复测一次确认",
    "建议连续记录并带给医生": "把早晚记录留下来带去复诊",
    "强调不自行调整用药": "用药别自己改",
    "建议记录并在复诊时提出": "把这阵子记录留好，复诊时提出",
    "给一个极低门槛动作：今天测一次就够": "今天测一次就好",
    "只请求一个最小动作：测一次": "今天测一次就好",
    "给一个维持动作": "照现在这样测就好",
}


def _fallback_fact(assessment: Assessment, playbook: dict, opening: str) -> str:
    signals = [str(item).strip() for item in (assessment.signals or []) if str(item).strip()]
    body = "；".join(signals) if signals else opening
    if assessment.sufficient is False:
        # 短声明放在事实层，长免责不进 disclaimers。
        prefix = "目前数据不足，我无法判断趋势。"
        return prefix if not body else f"{prefix}{body}"
    return body or opening


def _fallback_action(assessment: Assessment, playbook: dict, opening: str) -> str:
    # MONITORING_GAP / INSUFFICIENT_DATA / 升级路径保持原策略，只把其余状态接到 must_do。
    if assessment.escalation_required:
        phrase = _ESCALATION_PHRASE.get(
            assessment.escalation_action or "",
            "尽快就医",
        )
        return f"{phrase}。先复测一次确认。"
    if assessment.sufficient is False:
        return "今天测一次就行。"
    if assessment.state == "MONITORING_GAP":
        return "今天早起后测一次就行。"

    fragments: list[str] = []
    for item in (playbook or {}).get("must_do") or []:
        phrase = _MUST_DO_ACTION.get(str(item).strip())
        if phrase and phrase not in fragments:
            fragments.append(phrase)
        if len(fragments) == 2:
            break
    if not fragments:
        return opening or "今天测一次就行。"
    return "。".join(fragments) + "。"


def fallback(
    assessment: Assessment,
    playbook: dict,
    scene: str | None = None,
    user_query: str | None = None,
    history: list[dict[str, str]] | None = None,
    display_name: str | None = None,
) -> dict:
    """不调模型。推送看 scene；自由对话看 user_query；否则保持原 State 模板。"""
    if scene:
        return _fallback_with_scene(assessment, playbook, scene)
    if user_query:
        return _fallback_with_query(
            assessment, playbook, user_query, history, display_name
        )
    return _fallback_state_only(assessment, playbook)


def _fallback_state_only(assessment: Assessment, playbook: dict) -> dict:
    """原对话降级：opening + signals 出事实，must_do 出行动。eval 路径走这里。"""
    opening = str((playbook or {}).get("opening") or "").strip()
    fact = _fallback_fact(assessment, playbook, opening)
    action = _fallback_action(assessment, playbook, opening)
    return {
        "fact": fact or opening,
        "explain": opening or fact,
        "action": action,
        "escalation_action": assessment.escalation_action,
        "disclaimers": list((playbook or {}).get("disclaimers") or []),
    }


def _overlay_action(action: str, extra: str) -> str:
    parts = [part.strip("。；; ") for part in _ACTION_SPLIT_RE.split(action) if part.strip()]
    extra = extra.strip("。；; ")
    if extra and extra not in "".join(parts):
        if len(parts) >= 2:
            parts[-1] = extra
        else:
            parts.append(extra)
    return "。".join(parts[:2]) + "。" if parts else extra + "。"


def _must_do_patch(item: str, assessment: Assessment) -> str:
    """把 G4a 仍缺的 must_do 落成短句，数字只引用 Assessment。"""
    if "均值" in item and "达标" in item:
        mean = assessment.bp.get("sys_mean_7d")
        rate = assessment.bp.get("target_rate_30d")
        if mean is not None and rate is not None:
            return f"这周高压平均{float(mean):.0f}。最近测到的高压大多还在参考线以上。"
    if "晨晚差异" in item:
        from prompts.scenes import pattern_values_fact

        return pattern_values_fact(assessment)
    if "下降幅度" in item or "近14天" in item:
        compare = assessment.trend.get("compare_14d")
        if compare is not None:
            return f"近两周对比{float(compare):+.0f}。"
    return ""


def _apply_safety_overlay(
    assessment: Assessment,
    playbook: dict,
    fact: str,
    explain: str,
    action: str,
    extra_disclaimers: list[str] | None = None,
    skip_escalation_prompt: bool = False,
) -> dict:
    blob = fact + explain + action
    if (
        assessment.sufficient is False
        and "数据不足" not in blob
        and not skip_escalation_prompt
    ):
        fact = "目前数据不足，我无法判断趋势。" + fact
        blob = fact + explain + action

    if assessment.escalation_required and not skip_escalation_prompt:
        phrase = _ESCALATION_PHRASE.get(
            assessment.escalation_action or "",
            "尽快就医",
        )
        action = _overlay_action(action, phrase)
        blob = fact + explain + action
        if "读数" not in blob:
            explain = explain + "这次读数需要优先看。"
            blob = fact + explain + action
        if "复测" not in blob:
            explain = explain + "先复测一次确认。"
            blob = fact + explain + action

    if not skip_escalation_prompt:
        for item in (playbook or {}).get("must_do") or []:
            missed = _check_must_do_item(item, blob, assessment)
            if not missed:
                continue
            extra = _must_do_patch(item, assessment)
            if extra and extra not in blob:
                explain = explain + extra
                blob = fact + explain + action

    disclaimers = list((playbook or {}).get("disclaimers") or [])
    for item in extra_disclaimers or []:
        if item not in disclaimers:
            disclaimers.append(item)

    return {
        "fact": fact.strip(),
        "explain": explain.strip(),
        "action": action.strip(),
        "escalation_action": assessment.escalation_action,
        "disclaimers": disclaimers,
    }


def _fallback_with_scene(assessment: Assessment, playbook: dict, scene: str) -> dict:
    from prompts.scenes import fallback_draft

    draft = fallback_draft(assessment, scene)
    return _apply_safety_overlay(
        assessment,
        playbook,
        draft["fact"],
        draft["explain"],
        draft["action"],
    )


def _fallback_with_query(
    assessment: Assessment,
    playbook: dict,
    user_query: str,
    history: list[dict[str, str]] | None,
    display_name: str | None = None,
) -> dict:
    from prompts.intents import query_fallback_draft

    draft = query_fallback_draft(assessment, user_query, history, display_name)
    return _apply_safety_overlay(
        assessment,
        playbook,
        draft["fact"],
        draft["explain"],
        draft["action"],
        extra_disclaimers=list(draft.get("extra_disclaimers") or []),
        skip_escalation_prompt=bool(draft.get("skip_escalation_prompt")),
    )
