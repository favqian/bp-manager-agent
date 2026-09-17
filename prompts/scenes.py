"""推送场景卡：Scene 决定这次聊什么，不改变用户真实 State。"""

from __future__ import annotations

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
            "近7天/30天已有事实",
            "依从性、均值、晨晚差异、趋势等已有字段",
            "当前 State 对应的下一步行动",
        ],
        "must_focus": ["本周/近7天总结", "已有结构化指标", "下一步管理方向"],
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
        ]
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


def _pct(value: Any) -> str | None:
    if value is None:
        return None
    return f"{float(value):.0%}"


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
            return f"晨间{morning}、晚间{evening}，相差{delta_txt}。"
        return f"晨间{morning}、晚间{evening}。"
    if delta_txt is not None:
        return f"晨晚差{delta_txt}。"
    return ""


def _adherence_fact(assessment: Assessment) -> str:
    r7 = _pct(assessment.adherence.get("rate_7d"))
    r30 = _pct(assessment.adherence.get("rate_30d"))
    parts: list[str] = []
    if r7:
        parts.append(f"近7天依从率{r7}。")
    if r30:
        parts.append(f"30天依从率{r30}。")
    if not parts:
        days = assessment.adherence.get("days_since_last")
        if days is not None:
            parts.append(f"距上次测量{int(days)}天。")
    return "".join(parts)


def _anomaly_fact(assessment: Assessment) -> str:
    maximum = assessment.bp.get("max_single") or {}
    sys_max = maximum.get("sys")
    if sys_max is not None:
        return f"30天最高收缩压{_mm(sys_max)}。"
    delta = assessment.pattern.get("delta")
    morning = _mm(assessment.pattern.get("morning_mean"))
    evening = _mm(assessment.pattern.get("evening_mean"))
    if morning and evening and delta is not None:
        return pattern_values_fact(assessment)
    if delta is not None:
        return f"晨晚差{_mm(delta)}。"
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    if sys7:
        return f"近7天均值{sys7}。"
    return _adherence_fact(assessment)


def _summary_fact(assessment: Assessment) -> str:
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    r7 = _pct(assessment.adherence.get("rate_7d"))
    target = _pct(assessment.bp.get("target_rate_30d"))
    parts: list[str] = []
    if sys7:
        parts.append(f"近7天均值{sys7}。")
    if r7:
        parts.append(f"近7天依从率{r7}。")
    if target and len(parts) < 3:
        parts.append(f"30天达标率{target}。")
    if not parts:
        return _adherence_fact(assessment)
    return "".join(parts)


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
            return "尽快就医。把记录带去复诊。"
        return "尽快就医。先复测一次确认。"
    if assessment.sufficient is False:
        return "今天测一次就行。"
    if assessment.state == "MONITORING_GAP":
        return "今天早起后测一次就行。"
    if assessment.state == "MORNING_SURGE":
        return "把晨晚差记录下来。用药别自己改。"
    if assessment.state == "SUSTAINED_HIGH":
        return "把近窗记录下来，复诊时提出。"
    if assessment.state == "IMPROVING":
        return "继续观察，用药别自己改。"
    return "照现在这样测就行。"


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
        explain = "以上是近7天总结。" + safety
    else:
        raise KeyError(f"未知场景: {scene_id}")

    if assessment.sufficient is False and "数据不足" not in fact + explain:
        fact = "目前数据不足，我无法判断趋势。" + fact

    return {
        "fact": fact.strip() or "先看这次要做的事。",
        "explain": explain.strip() or "按当前管理状态处理。",
        "action": _scene_action(assessment, scene_id),
    }
