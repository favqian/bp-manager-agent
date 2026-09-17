"""推送场景卡：Scene 决定这次聊什么，不改变用户真实 State。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from contract import Assessment

SCENE_IDS = ("S1", "S2", "S3")

SCENES: dict[str, dict[str, Any]] = {
    "S1": {
        "id": "S1",
        "code": "ADHERENCE_REMINDER",
        "label": "依从提醒",
        "goal": "召回测量行为",
        "priority": [
            "当前测量/记录行为",
            "今天或下一次要做什么",
            "若 State 有更高优先级安全事项，再补充安全提醒",
        ],
        "must_focus": ["测量", "记录", "下一次行动"],
        "must_not": ["完整周报", "单纯异常通知"],
    },
    "S2": {
        "id": "S2",
        "code": "ANOMALY_RESPONSE",
        "label": "异常响应",
        "goal": "针对当前已知异常事实解释并给出下一步",
        "priority": [
            "哪个已知事实需要关注",
            "复测/确认",
            "若需要专业升级，明确下一步",
        ],
        "must_focus": ["异常事实", "复测", "专业关注/升级"],
        "must_not": ["周度总结", "普通测量提醒"],
    },
    "S3": {
        "id": "S3",
        "code": "WEEKLY_SUMMARY",
        "label": "周度总结",
        "goal": "总结最近一段时间的数据表现",
        "priority": [
            "最近7天最相关的事实",
            "当前 State 对应的下一步行动",
        ],
        "must_focus": ["本周/近7天总结", "下一步管理方向"],
        "must_not": ["单次异常通知", "单纯提醒今天测一次"],
    },
}


def get_scene(scene_id: str | None) -> dict[str, Any] | None:
    if not scene_id:
        return None
    card = SCENES.get(scene_id)
    if card is None:
        raise KeyError(f"未知场景: {scene_id}")
    return card


def format_instruction(scene: dict[str, Any]) -> str:
    """注入 Prompt 的场景层。State 安全边界优先，Scene 只组织这一次说什么。"""
    lines = [
        f"场景代码：{scene['id']} / {scene['code']}",
        f"场景名称：{scene['label']}",
        "规则：State 决定怎么管，Scene 决定这次聊什么。不得改写或替换管理状态。",
        f"本张卡片目标：{scene['goal']}",
        "内容优先级：",
    ]
    for index, item in enumerate(scene["priority"], start=1):
        lines.append(f"{index}. {item}")
    lines.append("必须明显围绕：" + "、".join(scene["must_focus"]))
    lines.append("不要写成：" + "、".join(scene["must_not"]))
    lines.extend(
        [
            "若当前 State 需要专业升级，必须保留升级提醒，但主主题仍是本场景，不能写成另一张场景卡。",
            "若数据不足，必须声明无法判断趋势，不能编趋势。",
            "所有数字只能引用【判读结果】已有事实，禁止自行计算或编造。",
            "不要写达标率、目标范围、目标范围内x%。140/90 是 Demo 参考线，不是治疗目标。",
            "默认不要报达标百分比。本周总结只写最近7天，不要塞30天依从率/达标率/最高值。",
        ]
    )
    if scene["id"] == "S3":
        lines.append(
            "例外：ESCALATION_REQUIRED 且最高读数不在近7天时，"
            "写「过去30天有一次高压到了x」，因为这影响当前安全策略。"
        )
    return "\n".join(lines)


def push_user_msg(scene_id: str) -> str:
    scene = get_scene(scene_id)
    if scene is None:
        raise KeyError(f"未知场景: {scene_id}")
    return (
        f"请生成一张【{scene['id']} {scene['label']}】推送卡片。"
        "严格按【本次场景说明】组织内容，按【当前状态策略卡】遵守安全边界。"
        "不得改变管理状态。只输出规定 JSON。不要编造数字。"
    )


def _mm(value: Any) -> str | None:
    if value is None:
        return None
    return f"{float(value):.0f}"


def pattern_values_fact(assessment: Assessment) -> str:
    """只引用 Assessment.pattern，不在本地做减法。"""
    morning = _mm(assessment.pattern.get("morning_mean"))
    evening = _mm(assessment.pattern.get("evening_mean"))
    delta = assessment.pattern.get("delta")
    delta_txt = _mm(delta) if delta is not None else None
    if morning and evening:
        if delta_txt is not None:
            return f"早上{morning}，晚上{evening}，相差{delta_txt}。"
        return f"早上{morning}，晚上{evening}。"
    if delta_txt is not None:
        return f"早上平均比晚上高{delta_txt}。"
    return ""


def _adherence_fact(assessment: Assessment) -> str:
    rate = assessment.adherence.get("rate_7d")
    if rate is None:
        days = assessment.adherence.get("days_since_last")
        if days is not None:
            return f"距上次测量{int(days)}天。"
        return ""
    if float(rate) < 0.3:
        return "这周测得比较少。"
    if float(rate) >= 0.8:
        return "这周基本都有测。"
    return "这周有一部分日子测过了。"


def crisis_reading_fact(assessment: Assessment) -> str:
    """安全相关最高读数。超出近7天时标明过去30天，避免写进「本周」。"""
    maximum = assessment.bp.get("max_single") or {}
    high = _mm(maximum.get("sys"))
    if not high:
        return "有一次读数需要优先处理。"
    date = maximum.get("date")
    as_of = assessment.as_of
    label = "最近"
    if date and as_of:
        try:
            start = datetime.strptime(str(date)[:10], "%Y-%m-%d")
            end = datetime.strptime(str(as_of)[:10], "%Y-%m-%d")
            if (end - start).days > 7:
                label = "过去30天"
        except ValueError:
            label = "过去30天"
    return f"{label}有一次高压到了{high}。"


def _anomaly_fact(assessment: Assessment) -> str:
    maximum = assessment.bp.get("max_single") or {}
    sys_max = maximum.get("sys")
    if sys_max is not None:
        return crisis_reading_fact(assessment)
    delta = assessment.pattern.get("delta")
    morning = _mm(assessment.pattern.get("morning_mean"))
    evening = _mm(assessment.pattern.get("evening_mean"))
    if morning and evening and delta is not None:
        return pattern_values_fact(assessment)
    if delta is not None:
        return f"早上平均比晚上高{_mm(delta)}。"
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    if sys7:
        return f"这周高压平均{sys7}。"
    return _adherence_fact(assessment)


def _summary_fact(assessment: Assessment) -> str:
    """本周总结：按 State 选题，默认近7天，不翻译 target_rate。"""
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    direction = (assessment.trend or {}).get("direction")
    if assessment.escalation_required:
        return crisis_reading_fact(assessment)
    if assessment.state == "MONITORING_GAP":
        return "这周测得比较少。"
    if assessment.state == "SUSTAINED_HIGH":
        parts: list[str] = []
        if sys7:
            parts.append(f"这周高压平均{sys7}。")
        if direction == "improving":
            parts.append("最近数字有往下走。")
        return "".join(parts) or _adherence_fact(assessment)
    parts = [_adherence_fact(assessment)]
    if sys7:
        parts.append(f"这周高压平均{sys7}。")
    text = "".join(part for part in parts if part)
    return text or _adherence_fact(assessment)


def _summary_explain(assessment: Assessment) -> str:
    if assessment.escalation_required:
        return "这次需要优先处理。"
    if assessment.state == "MONITORING_GAP":
        return "现在还看不出明显变化。"
    if assessment.state == "SUSTAINED_HIGH":
        return "这周整体还是偏高。"
    return "以上是这周的情况。"


def _safety_explain(assessment: Assessment) -> str:
    parts: list[str] = []
    if assessment.sufficient is False:
        parts.append("目前数据不足，我无法判断趋势。")
    if assessment.escalation_required:
        parts.append("有一次读数要看。")
        parts.append("先复测确认。")
    return "".join(parts)


def _scene_action(assessment: Assessment, scene_id: str) -> str:
    if assessment.escalation_required:
        if scene_id == "S1":
            return "今天测一次记下。尽快就医。"
        if scene_id == "S3":
            return "先复测一次。尽快就医。"
        return "尽快就医。先复测一次确认。"
    if assessment.sufficient is False:
        return "今天测一次就行。"
    if assessment.state == "MONITORING_GAP":
        if scene_id == "S3":
            return "今天先测一次，把记录接上。"
        return "今天早起后测一次就好。"
    if assessment.state == "MORNING_SURGE":
        return "把早晚记录留下来。用药别自己改。"
    if assessment.state == "SUSTAINED_HIGH":
        return "把最近记录留好，复诊时给医生看。"
    if assessment.state == "IMPROVING":
        return "继续观察，用药别自己改。"
    return "照现在这样测就好。"


def fallback_draft(assessment: Assessment, scene_id: str) -> dict[str, str]:
    """Scene-aware 降级草稿。数字只来自 Assessment；安全句由 Guard 再覆盖一层。"""
    safety = _safety_explain(assessment)
    if scene_id == "S1":
        fact = _adherence_fact(assessment)
        explain = "这次先把测量接上。" + safety
    elif scene_id == "S2":
        fact = _anomaly_fact(assessment)
        if assessment.escalation_required:
            explain = "这次读数需要关注。"
            if assessment.sufficient is False:
                explain = "目前数据不足，我无法判断趋势。" + explain
        else:
            explain = "这次异常需要确认。先复测一次。"
            if assessment.sufficient is False:
                explain = "目前数据不足，我无法判断趋势。"
    elif scene_id == "S3":
        fact = _summary_fact(assessment)
        explain = _summary_explain(assessment)
        if assessment.sufficient is False:
            explain = explain + safety
    else:
        raise KeyError(f"未知场景: {scene_id}")

    if assessment.sufficient is False and "数据不足" not in fact + explain:
        fact = "目前数据不足，我无法判断趋势。" + fact

    return {
        "fact": fact.strip() or "先看这次要做的事。",
        "explain": explain.strip() or "按当前管理状态处理。",
        "action": _scene_action(assessment, scene_id),
    }
