"""State 之后的执行层。不计算血压，不改路由。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from contract import Assessment
from prompts.scenes import _mm, crisis_reading_fact

RESTORE_ROUTINE = "RESTORE_ROUTINE"
CLINICAL_HANDOFF = "CLINICAL_HANDOFF"
MAINTAIN_PROGRESS = "MAINTAIN_PROGRESS"

TRIGGER_OPTIONS = ("起床洗漱后", "早餐前", "自己定一个")

_MEASURE_DONE = ("我测了", "测了", "已测", "测过了", "今天测了")
_VISIT_READY = ("准备去医院", "去医院", "准备就医", "去看医生", "去看病")
_KEEP_RHYTHM = ("继续这样测", "继续测", "保持这样", "继续按现在")


@dataclass
class ActionPlan:
    action_type: str
    title: str
    action_goal: str
    primary_action: str
    execution_support: str
    success_criteria: str
    follow_up: str
    failure_adapt: str
    status: str = "pending"
    user_choice: str | None = None
    result: str | None = None
    trigger_node: str | None = None
    custom_trigger: str | None = None
    friction: str | None = None
    handoff_text: str | None = None
    remeasured: bool = False
    ready_to_visit: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionPlan":
        allowed = {key: payload.get(key) for key in cls.__dataclass_fields__}
        allowed["extras"] = payload.get("extras") or {}
        return cls(**allowed)

    def trigger_label(self) -> str:
        if self.trigger_node == "自己定一个" and self.custom_trigger:
            return self.custom_trigger
        return self.trigger_node or "一个固定生活节点"


def _pct_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def _date_label(raw: Any) -> str | None:
    if not raw:
        return None
    text = str(raw)[:10]
    try:
        value = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return text
    return f"{value.month}月{value.day}日"


def _compare_text(assessment: Assessment) -> str | None:
    compare = (assessment.trend or {}).get("compare_14d")
    if compare is None:
        return None
    if float(compare) < 0:
        return "近两周相对前一阶段更低。"
    if float(compare) > 0:
        return "近两周相对前一阶段更高。"
    return "近两周相对前一阶段变化不大。"


def build_action_plan(assessment: Assessment) -> ActionPlan:
    """只读 Assessment.state，生成当前执行计划。"""
    state = assessment.state or ""
    if state == "ESCALATION_REQUIRED" or assessment.escalation_required:
        return ActionPlan(
            action_type=CLINICAL_HANDOFF,
            title="就诊准备",
            action_goal="降低从发现异常到专业处理的摩擦",
            primary_action="先按规范复测一次确认，并尽快就医。",
            execution_support="整理一份就诊摘要，去的时候直接给医生看。",
            success_criteria="已复测，或已准备好摘要并准备就医",
            follow_up="下次先问：复测做了吗？医生看过这次读数了吗？",
            failure_adapt="未复测也可先备好摘要，仍不取消就医。",
        )
    if state == "MONITORING_GAP":
        return ActionPlan(
            action_type=RESTORE_ROUTINE,
            title="恢复测量计划",
            action_goal="恢复监测节奏",
            primary_action="今天先完成下一次既定测量。",
            execution_support="把这次测量绑到一个容易记住的生活节点。",
            success_criteria="今天形成一次新的有效记录",
            follow_up="下次先看这个节奏有没有接起来。",
            failure_adapt="不问责；问是容易忘还是时间不方便，再改提醒方式。",
            trigger_node="起床洗漱后",
        )
    if state == "SUSTAINED_HIGH":
        return ActionPlan(
            action_type=MAINTAIN_PROGRESS,
            title="趋势验证计划",
            action_goal="巩固现有监测，并验证下降是否持续",
            primary_action="先保持现在的测量节奏，暂时不增加新任务。",
            execution_support="新增一周记录后，用同样口径再比较一次。",
            success_criteria="近7天节奏不掉，下一对比窗再看变化是否保持",
            follow_up="下一次总结继续看：这个下降能不能保持住。",
            failure_adapt="若开始漏测，先问节奏是否断了，不加无关任务。",
            extras={"phase": "observe", "next_phase": "verify"},
        )
    return ActionPlan(
        action_type=MAINTAIN_PROGRESS,
        title="本周行动计划",
        action_goal="按当前管理状态完成下一步",
        primary_action="继续按现在这样测。",
        execution_support="先不加新的管理任务。",
        success_criteria="本周保持现有测量",
        follow_up="下次再看记录有没有变化。",
        failure_adapt="降低到一次测量即可。",
    )


def health_summary_view(assessment: Assessment) -> dict[str, Any]:
    """理解层：1 个洞察 + 最多 2 条不同槽位的证据。不含 Action。"""
    state = assessment.state or ""
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    rate7 = _pct_int(assessment.adherence.get("rate_7d"))
    direction = (assessment.trend or {}).get("direction")
    maximum = assessment.bp.get("max_single") or {}
    date_txt = _date_label(maximum.get("date"))
    high = _mm(maximum.get("sys"))
    low = _mm(maximum.get("dia"))

    if state == "MONITORING_GAP":
        evidence = ["这周只有少量测量记录。"]
        if sys7:
            evidence.append(f"已有记录里高压平均{sys7}，仍偏高，但记录不连续，这周先不判断变化。")
        return {
            "insight": "最近记录断得比较多。现在最重要的是先把测量节奏接回来。",
            "evidence": evidence[:2],
        }

    if state == "ESCALATION_REQUIRED":
        date_txt = _date_label(maximum.get("date"))
        low = _mm(maximum.get("dia"))
        event_bits = []
        if date_txt:
            event_bits.append(f"发生在{date_txt}")
        if low:
            event_bits.append(f"低压{low}")
        event = "，".join(event_bits) + "。" if event_bits else crisis_reading_fact(assessment)
        evidence = [event]
        if rate7 is not None and rate7 >= 70:
            evidence.append("这周记录比较完整，可以把最近一周和这次异常一起带去。")
        return {
            "insight": f"{crisis_reading_fact(assessment).rstrip('。')}。这件事比平均值更值得优先处理。",
            "evidence": evidence[:2],
        }

    if state == "SUSTAINED_HIGH":
        evidence = []
        if sys7:
            evidence.append(f"这周高压平均{sys7}。")
        trend_txt = _compare_text(assessment)
        if trend_txt:
            evidence.append(trend_txt)
        if direction == "improving":
            insight = "这周整体还是偏高；同时近两周已经出现下降。本周先巩固，再验证。"
        else:
            insight = "这周整体还是偏高。本周先保持现有节奏，不另加任务。"
        return {"insight": insight, "evidence": evidence[:2]}

    if sys7:
        return {
            "insight": "先看这周最需要处理的一件事。",
            "evidence": [f"这周高压平均{sys7}。"],
        }
    return {"insight": "先看最近的记录。", "evidence": ["按当前管理状态继续。"]}


def build_visit_summary(assessment: Assessment) -> str:
    """就诊摘要：只整理 Assessment 已有事实，不做诊断。"""
    maximum = assessment.bp.get("max_single") or {}
    date_txt = _date_label(maximum.get("date")) or "近期"
    high = _mm(maximum.get("sys")) or "—"
    low = _mm(maximum.get("dia")) or "—"
    sys7 = _mm(assessment.bp.get("sys_mean_7d"))
    dia7 = _mm(assessment.bp.get("dia_mean_7d"))
    morning = _mm((assessment.pattern or {}).get("morning_mean"))
    evening = _mm((assessment.pattern or {}).get("evening_mean"))
    delta = (assessment.pattern or {}).get("delta")
    rate7 = _pct_int(assessment.adherence.get("rate_7d"))

    focus = [f"{date_txt}：高压{high}，低压{low}"]
    if sys7:
        line = f"这周高压平均{sys7}"
        if dia7:
            line += f"，低压平均{dia7}"
        focus.append(line + "。")
    if (
        delta is not None
        and float(delta) >= 10
        and morning
        and evening
    ):
        focus.append(f"早上平均{morning}，晚上平均{evening}，可作为辅助记录。")

    overview = []
    if rate7 is not None and rate7 >= 70:
        overview.append("这周大部分时间都有测。")
    elif rate7 is not None:
        overview.append("这周也有在测。")
    if delta is not None and float(delta) >= 10:
        overview.append("早上的读数比晚上高一些。")
    if not overview:
        overview.append("以上是目前已有记录里最需要带去的部分。")

    questions = [
        "这次异常需要重点关注什么？",
        "后续测量需要重点记录哪些时间段？",
        "复诊时还需要准备哪些记录？",
    ]
    lines = ["【需要重点告诉医生】"]
    lines.extend(f"- {item}" for item in focus)
    lines.append("")
    lines.append("【最近记录概况】")
    lines.extend(f"- {item}" for item in overview[:2])
    lines.append("")
    lines.append("【我想问医生】")
    lines.extend(f"- {item}" for item in questions)
    lines.append("")
    lines.append("说明：这是就诊准备材料，不是诊断，也不是用药建议。")
    return "\n".join(lines)


def classify_execution_event(query: str, plan: ActionPlan | None) -> str | None:
    text = (query or "").strip()
    if not text or plan is None:
        return None
    if any(key in text for key in _MEASURE_DONE):
        if "忘了测" in text or "忘记测" in text or "没测" in text:
            return None
        return "measure_done"
    if any(key in text for key in _VISIT_READY):
        return "visit_ready"
    if any(key in text for key in _KEEP_RHYTHM):
        return "keep_rhythm"
    if text in ("还没测", "还没有测"):
        return "measure_skip"
    return None


def apply_event(plan: ActionPlan, event: str, value: str | None = None) -> ActionPlan:
    if event == "set_trigger":
        plan.trigger_node = value or plan.trigger_node
        if value != "自己定一个":
            plan.custom_trigger = None
        plan.execution_support = f"绑在「{plan.trigger_label()}」这一次就行。"
    elif event == "set_custom_trigger":
        plan.custom_trigger = (value or "").strip() or None
        plan.trigger_node = "自己定一个"
        if plan.custom_trigger:
            plan.execution_support = f"绑在「{plan.custom_trigger}」这一次就行。"
    elif event == "measure_done":
        plan.status = "done"
        plan.result = "today_measured"
        plan.friction = None
    elif event == "measure_skip":
        plan.status = "skipped"
        plan.result = "not_today"
    elif event == "friction_forget":
        plan.friction = "forget"
        plan.user_choice = "容易忘"
        plan.execution_support = "可以给这个时间点加个手机提醒。设备也放在容易看到的地方。"
        plan.status = "pending"
    elif event == "friction_inconvenient":
        plan.friction = "inconvenient"
        plan.user_choice = "时间不方便"
        plan.execution_support = "换一个更容易做到的时间点，再绑一次。"
        plan.status = "pending"
    elif event == "generate_handoff":
        plan.handoff_text = value
        plan.result = "handoff_ready"
    elif event == "remeasured":
        plan.remeasured = True
        plan.result = "remeasured"
    elif event == "ready_to_visit":
        plan.ready_to_visit = True
        plan.status = "done"
        plan.result = "ready_to_visit"
    elif event == "keep_rhythm":
        plan.status = "pending"
        plan.result = "keep_rhythm"
    return plan


def execution_reply(plan: ActionPlan, event: str) -> dict[str, str]:
    """执行回告的确定性回复。不走模型，避免 Guard 把已完成动作再催一遍。"""
    if event == "measure_done":
        node = plan.trigger_label()
        return {
            "fact": "这次接上了。",
            "explain": f"先保持「{node}」这个节点就行。",
            "action": "后面我继续帮你看记录有没有接起来。",
        }
    if event == "measure_skip":
        return {
            "fact": "今天还没接上，也没关系。",
            "explain": "是容易忘，还是这个时间不方便？",
            "action": "说一下，我帮你改提醒方式。",
        }
    if event == "visit_ready":
        extra = "可以把刚才整理的摘要一起带上。" if plan.handoff_text else "需要的话，我可以先帮你整理就诊摘要。"
        return {
            "fact": "那就先把这次读数带去给医生看。",
            "explain": extra,
            "action": "去之前仍先按规范复测一次。",
        }
    if event == "keep_rhythm":
        return {
            "fact": "可以，先保持现在的测量节奏。",
            "explain": "暂时不增加新的管理任务。",
            "action": "下一次我继续帮你看这个变化能不能保持。",
        }
    return {
        "fact": "我记下了。",
        "explain": "按眼前这份计划继续就行。",
        "action": plan.primary_action,
    }


def plan_brief(plan: ActionPlan) -> str:
    return (
        f"类型：{plan.action_type}\n"
        f"标题：{plan.title}\n"
        f"目标：{plan.action_goal}\n"
        f"主行动：{plan.primary_action}\n"
        f"执行支持：{plan.execution_support}\n"
        f"状态：{plan.status}\n"
        f"节点：{plan.trigger_label()}\n"
        "用户若在汇报执行，不要重写周报，围绕这份计划短答。"
    )
