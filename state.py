# 设计前提：
# - risk_level 是描述性指标，仅作为状态判断的辅助信号，不直接驱动 Agent 行为；
# - state 才是 Agent 的行为路由依据；
# - 数据流：原始数据 → 规则计算 → 管理状态 → AI 策略；
# - 所有状态触发阈值均来自 params.py；state.py 负责路由，不负责定义参数，
#   本文件不得出现任何裸数字阈值。

"""状态机路由 + 状态策略卡。只读 params，不计算血压数值。"""

from __future__ import annotations

import pandas as pd

import params
from contract import Assessment, ManagementState
from rules import DEMO_PATIENTS, assess

# decide_state 优先级（高 → 低）：
# 1) a.escalation_required                                          -> ESCALATION_REQUIRED
# 2) not a.sufficient                                               -> INSUFFICIENT_DATA
# 3) a.adherence.rate_7d < p.STATE.monitoring_gap_rate
#    或 a.adherence.days_since_last >= p.STATE.monitoring_gap_days  -> MONITORING_GAP
# 4) a.pattern.stable_delta 且 a.pattern.delta >= p.STATE.morning_surge_delta
#                                                                   -> MORNING_SURGE
# 5) a.risk_level in ("high", "moderate")                           -> SUSTAINED_HIGH
#    第 5 条只把 risk_level 当作辅助信号，不是把风险等级直接映射为行为。
# 6) a.trend.direction == "improving"                               -> IMPROVING
# 7) 其余                                                           -> STABLE_MAINTAIN

_AUX_RISK_SIGNALS = frozenset({"high", "moderate"})
_TREND_IMPROVING = "improving"


def decide_state(a: Assessment, p=params) -> str:
    """按优先级把 Assessment 路由到管理状态。阈值只读 params.STATE。"""
    if a.escalation_required:
        return ManagementState.ESCALATION_REQUIRED.value

    if not a.sufficient:
        return ManagementState.INSUFFICIENT_DATA.value

    rate_7d = a.adherence.get("rate_7d")
    days_since_last = a.adherence.get("days_since_last")
    gap_by_rate = rate_7d is not None and rate_7d < p.STATE.monitoring_gap_rate
    gap_by_days = (
        days_since_last is not None
        and days_since_last >= p.STATE.monitoring_gap_days
    )
    if gap_by_rate or gap_by_days:
        return ManagementState.MONITORING_GAP.value

    delta = a.pattern.get("delta")
    if (
        bool(a.pattern.get("stable_delta"))
        and delta is not None
        and delta >= p.STATE.morning_surge_delta
    ):
        return ManagementState.MORNING_SURGE.value

    if a.risk_level in _AUX_RISK_SIGNALS:
        return ManagementState.SUSTAINED_HIGH.value

    if a.trend.get("direction") == _TREND_IMPROVING:
        return ManagementState.IMPROVING.value

    return ManagementState.STABLE_MAINTAIN.value


STATE_PLAYBOOK: dict[str, dict] = {
    ManagementState.ESCALATION_REQUIRED.value: {
        "goal": "让用户尽快获得专业人员关注与处理，不讨论数据细节",
        "tone": "冷静、明确、不制造恐慌",
        "must_do": [
            "给出明确的升级动作（contact_doctor / seek_professional_help）",
            "说明是哪次读数触发",
            "提示规范复测确认",
        ],
        "must_not": [
            "不解释病因",
            "不推测后果",
            "不评价风险等级高低",
        ],
        "disclaimers": ["非诊断声明"],
        "escalation_action": "seek_professional_help",
        "opening": "先说重要的：有一次读数需要尽快让医生看一下。",
    },
    ManagementState.INSUFFICIENT_DATA.value: {
        "goal": "要回一次测量，不做任何趋势判断",
        "tone": "轻松、不施压、不问责",
        "must_do": [
            "明确说「目前数据不足，我无法判断趋势」",
            "只请求一个最小动作：测一次",
        ],
        "must_not": [
            "不推断血压好坏",
            "不提「您最近没测」或「不配合」",
        ],
        "disclaimers": ["数据不足声明"],
        "opening": "最近记录有点少，我暂时看不出趋势。",
    },
    ManagementState.MONITORING_GAP.value: {
        "goal": "低打扰地把测量习惯找回来",
        "tone": "陪伴、去羞耻化（漏测归因于「忙/忘」，不是「不听话」）",
        "must_do": [
            "给一个极低门槛动作：今天测一次就够",
            "给固定时点建议（早起后）",
        ],
        "must_not": [
            "一次给多个任务",
            "说教",
            "用「应该/必须」",
        ],
        "disclaimers": ["数据不足声明"],
        "opening": "这两天忙忘了吧？今天测一次就行。",
    },
    ManagementState.MORNING_SURGE.value: {
        "goal": "把「早上高、晚上低」这个规律讲清楚，并带去复诊",
        "tone": "平静、就事论事",
        "must_do": [
            "说明晨晚差异的具体数值",
            "建议连续记录并带给医生",
            "强调不自行调整用药",
        ],
        "must_not": [
            "不建议自行改服药时间",
            "不推测原因",
            "不用「危险」字样",
        ],
        "disclaimers": ["非因果声明", "非诊断声明"],
        "opening": "有个规律值得记下来：早上比晚上高。",
    },
    ManagementState.SUSTAINED_HIGH.value: {
        "goal": "让用户知道「整体偏高」，记录并复诊",
        "tone": "直接、不带焦虑",
        "must_do": [
            "给出近7天均值和达标比例",
            "建议记录并在复诊时提出",
        ],
        "must_not": [
            "不做病因解释",
            "不与他人比较",
        ],
        "disclaimers": ["非因果声明"],
        "opening": "整体看，最近一周的血压偏高一些。",
    },
    ManagementState.IMPROVING.value: {
        "goal": "确认过程、稳住行为，不做疗效承诺",
        "tone": "肯定过程，不夸张",
        "must_do": [
            "说明近14天 vs 前14天的下降幅度",
            "把变化归到「坚持测量和生活方式」的过程上",
            "提醒继续观察、不停药",
        ],
        "must_not": [
            "禁用「治愈/痊愈/恢复正常/可以停药」",
            "不把同期变化说成因果",
        ],
        "disclaimers": ["非因果声明", "非治愈声明"],
        "opening": "这半个月在往下走，值得肯定。",
    },
    ManagementState.STABLE_MAINTAIN.value: {
        "goal": "保持现状，减少打扰",
        "tone": "简短、平稳",
        "must_do": [
            "确认当前状态",
            "给一个维持动作",
        ],
        "must_not": [
            "制造新问题",
            "过度提醒",
        ],
        "disclaimers": [],
        "opening": "目前看起来比较平稳。",
    },
}


def get_playbook(state: str) -> dict:
    try:
        return STATE_PLAYBOOK[state]
    except KeyError as exc:
        raise KeyError(f"未知管理状态: {state}") from exc


def main() -> None:
    rows = []
    for patient_id in DEMO_PATIENTS:
        assessment = assess(patient_id)
        state = decide_state(assessment)
        card = get_playbook(state)
        print("=" * 60)
        print(f"{patient_id}  →  {state}")
        print(f"risk_level（参考）: {assessment.risk_level}")
        print(f"goal   : {card['goal']}")
        print(f"opening: {card['opening']}")
        rows.append(
            {
                "patient_id": patient_id,
                "state": state,
                "risk_level": assessment.risk_level,
                "goal": card["goal"],
                "opening": card["opening"],
            }
        )

    print("\n" + "=" * 60)
    print("对照表")
    print(pd.DataFrame(rows).to_string(index=False))
    states = {row["state"] for row in rows}
    if len(states) == len(rows):
        print("验收：三人进入不同状态、触发不同策略卡。")
    else:
        print("提示：出现了相同状态，请核对优先级与输入。")


if __name__ == "__main__":
    main()
