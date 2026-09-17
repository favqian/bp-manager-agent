"""按状态动态注入的 few-shot 示例库。目标是校准表达风格，不是堆积数量。

先收录核心三状态供语气审阅；其余四状态待确认后再补，合计 14 条，不多写。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import Assessment, ManagementState

_REQUIRED_INSUFFICIENT = "目前数据不足，我无法判断趋势"


def _dump(reply: dict) -> str:
    return json.dumps(reply, ensure_ascii=False, indent=2)


def _user(assessment: Assessment, question: str) -> str:
    return "【判读结果】\n" + assessment.to_json() + "\n\n" + question


def _gap() -> Assessment:
    return Assessment(
        patient_id="fewshot_gap",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={
            "days": 30,
            "valid_measurements": 46,
            "expected": 60,
            "coverage_rate": 0.77,
        },
        adherence={
            "rate_30d": 0.77,
            "rate_7d": 0.14,
            "max_gap_days": 3,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 156,
            "sys_sd_7d": 14.8,
            "dia_mean_7d": 94,
            "sys_mean_30d": 153,
            "target_rate_30d": 0.08,
            "max_single": {"sys": 172, "dia": 98, "date": "2026-01-11"},
        },
        pattern={
            "morning_mean": 153,
            "evening_mean": 152,
            "delta": 1,
            "stable_delta": False,
            "paired_days": 21,
        },
        trend={"slope_per_week": 0.4, "direction": "stable", "compare_14d": 1},
        activity={"steps_mean_7d": 2600, "steps_delta": -180, "hr_mean_7d": 88},
        risk_level="moderate",
        state=ManagementState.MONITORING_GAP.value,
        escalation_required=False,
        escalation_action=None,
        signals=["近窗依从率0.14", "近窗均值156"],
        required_disclaimers=["数据不足声明"],
        needs_human=False,
        human_route=None,
    )


def _escalate() -> Assessment:
    return Assessment(
        patient_id="fewshot_escalate",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={
            "days": 30,
            "valid_measurements": 51,
            "expected": 60,
            "coverage_rate": 0.85,
        },
        adherence={
            "rate_30d": 0.85,
            "rate_7d": 0.86,
            "max_gap_days": 1,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 142,
            "sys_sd_7d": 13.5,
            "dia_mean_7d": 89,
            "sys_mean_30d": 144,
            "target_rate_30d": 0.28,
            "max_single": {"sys": 185, "dia": 102, "date": "2026-01-17"},
        },
        pattern={
            "morning_mean": 152,
            "evening_mean": 137,
            "delta": 15,
            "stable_delta": True,
            "paired_days": 22,
        },
        trend={"slope_per_week": 1.0, "direction": "stable", "compare_14d": 4},
        activity={"steps_mean_7d": 5900, "steps_delta": 200, "hr_mean_7d": 78},
        risk_level="high",
        state=ManagementState.ESCALATION_REQUIRED.value,
        escalation_required=True,
        escalation_action="seek_professional_help",
        signals=["单次收缩压185"],
        required_disclaimers=["非诊断声明"],
        needs_human=True,
        human_route="seek_professional_help",
    )


def _sustained() -> Assessment:
    return Assessment(
        patient_id="fewshot_sustained",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={
            "days": 30,
            "valid_measurements": 30,
            "expected": 30,
            "coverage_rate": 1.0,
        },
        adherence={
            "rate_30d": 1.0,
            "rate_7d": 1.0,
            "max_gap_days": 0,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 156,
            "sys_sd_7d": 4.2,
            "dia_mean_7d": 94,
            "sys_mean_30d": 151,
            "target_rate_30d": 0.08,
            "max_single": {"sys": 163, "dia": 90, "date": "2026-01-06"},
        },
        pattern={
            "morning_mean": None,
            "evening_mean": None,
            "delta": None,
            "stable_delta": False,
            "paired_days": 0,
        },
        trend={"slope_per_week": -1.0, "direction": "stable", "compare_14d": -2},
        activity={"steps_mean_7d": 5000, "steps_delta": 100, "hr_mean_7d": 80},
        risk_level="moderate",
        state=ManagementState.SUSTAINED_HIGH.value,
        escalation_required=False,
        escalation_action=None,
        signals=["近窗均值156", "达标比例0.08"],
        required_disclaimers=["非因果声明"],
        needs_human=False,
        human_route=None,
    )


def _insufficient() -> Assessment:
    return Assessment(
        patient_id="fewshot_insufficient",
        as_of="2026-01-30",
        sufficient=False,
        sufficient_reason="近30天有效测量不足",
        window={
            "days": 30,
            "valid_measurements": 3,
            "expected": 60,
            "coverage_rate": 0.05,
        },
        adherence={
            "rate_30d": 0.05,
            "rate_7d": 0.0,
            "max_gap_days": 27,
            "last_measure_date": "2026-01-03",
            "days_since_last": 27,
        },
        bp={
            "sys_mean_7d": None,
            "sys_sd_7d": None,
            "dia_mean_7d": None,
            "sys_mean_30d": 149,
            "target_rate_30d": 0.0,
            "max_single": {"sys": 151, "dia": 94, "date": "2026-01-02"},
        },
        pattern={
            "morning_mean": None,
            "evening_mean": None,
            "delta": None,
            "stable_delta": False,
            "paired_days": 0,
        },
        trend={"slope_per_week": None, "direction": "unknown", "compare_14d": None},
        activity={"steps_mean_7d": None, "steps_delta": None, "hr_mean_7d": None},
        risk_level="unknown",
        state=ManagementState.INSUFFICIENT_DATA.value,
        escalation_required=False,
        escalation_action=None,
        signals=["覆盖率0.05", "近窗依从率0.0"],
        required_disclaimers=["数据不足声明"],
        needs_human=False,
        human_route=None,
    )


def _morning() -> Assessment:
    return Assessment(
        patient_id="fewshot_morning",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={
            "days": 30,
            "valid_measurements": 51,
            "expected": 60,
            "coverage_rate": 0.85,
        },
        adherence={
            "rate_30d": 0.85,
            "rate_7d": 0.86,
            "max_gap_days": 1,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 145,
            "sys_sd_7d": 13.5,
            "dia_mean_7d": 89,
            "sys_mean_30d": 144,
            "target_rate_30d": 0.28,
            "max_single": {"sys": 168, "dia": 98, "date": "2026-01-12"},
        },
        pattern={
            "morning_mean": 152,
            "evening_mean": 137,
            "delta": 15,
            "stable_delta": True,
            "paired_days": 22,
        },
        trend={"slope_per_week": 1.0, "direction": "stable", "compare_14d": 4},
        activity={"steps_mean_7d": 5900, "steps_delta": 200, "hr_mean_7d": 78},
        risk_level="moderate",
        state=ManagementState.MORNING_SURGE.value,
        escalation_required=False,
        escalation_action=None,
        signals=["晨间152、晚间137，差15"],
        required_disclaimers=["非因果声明", "非诊断声明"],
        needs_human=False,
        human_route=None,
    )


def _improving() -> Assessment:
    return Assessment(
        patient_id="fewshot_improving",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={
            "days": 30,
            "valid_measurements": 30,
            "expected": 30,
            "coverage_rate": 1.0,
        },
        adherence={
            "rate_30d": 1.0,
            "rate_7d": 1.0,
            "max_gap_days": 0,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 142,
            "sys_sd_7d": 4.2,
            "dia_mean_7d": 87,
            "sys_mean_30d": 151,
            "target_rate_30d": 0.07,
            "max_single": {"sys": 163, "dia": 90, "date": "2026-01-06"},
        },
        pattern={
            "morning_mean": None,
            "evening_mean": None,
            "delta": None,
            "stable_delta": False,
            "paired_days": 0,
        },
        trend={"slope_per_week": -4.4, "direction": "improving", "compare_14d": -8},
        activity={"steps_mean_7d": 6200, "steps_delta": 900, "hr_mean_7d": 83},
        risk_level="moderate",
        state=ManagementState.IMPROVING.value,
        escalation_required=False,
        escalation_action=None,
        signals=["对比变化-8", "近窗收缩压142", "步数6200"],
        required_disclaimers=["非因果声明", "非治愈声明"],
        needs_human=False,
        human_route=None,
    )


_A_INSUFF = _insufficient()
_A_MORNING = _morning()
_A_IMPROVE = _improving()
_A_GAP = _gap()
_A_ESCALATE = _escalate()
_A_SUSTAINED = _sustained()

FEWSHOTS: dict[str, list[dict[str, str]]] = {
    ManagementState.INSUFFICIENT_DATA.value: [
        {
            "user": _user(_A_INSUFF, "我最近怎么样？"),
            "assistant": _dump(
                {
                    "fact": f"{_REQUIRED_INSUFFICIENT}。",
                    "explain": "最近记录还少。现在还看不出变化。",
                    "action": "今天测一次就好。",
                    "escalation_action": None,
                    "disclaimers": ["数据不足声明"],
                }
            ),
        },
        {
            "user": _user(_A_INSUFF, "为什么这几天总是偏高？"),
            "assistant": _dump(
                {
                    "fact": f"{_REQUIRED_INSUFFICIENT}。",
                    "explain": "现在还看不出是高是稳。",
                    "action": "今天测一次就好。",
                    "escalation_action": None,
                    "disclaimers": ["数据不足声明", "非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_INSUFF, "我是不是要中风了？"),
            "assistant": _dump(
                {
                    "fact": f"{_REQUIRED_INSUFFICIENT}。",
                    "explain": "那种严重判断我做不了。现在缺的是测量。",
                    "action": "今天测一次就好。",
                    "escalation_action": None,
                    "disclaimers": ["数据不足声明", "非诊断声明"],
                }
            ),
        },
    ],
    ManagementState.MORNING_SURGE.value: [
        {
            "user": _user(_A_MORNING, "我最近怎么样？"),
            "assistant": _dump(
                {
                    "fact": "早上平均比晚上高15。",
                    "explain": "早上的读数比晚上高一些。",
                    "action": "把早晚记录留下来。用药别自己改。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_MORNING, "为什么这几天总是偏高？"),
            "assistant": _dump(
                {
                    "fact": "早上平均比晚上高15。",
                    "explain": "不是全天都高。主要是早上这一截。",
                    "action": "把早晚记录留下来。用药别自己改。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_MORNING, "我是不是要中风了？"),
            "assistant": _dump(
                {
                    "fact": "早上平均比晚上高15。",
                    "explain": "我不能根据数字猜后果。",
                    "action": "把早晚记录留下来。用药别自己改。",
                    "escalation_action": None,
                    "disclaimers": ["非诊断声明", "非因果声明"],
                }
            ),
        },
    ],
    ManagementState.IMPROVING.value: [
        {
            "user": _user(_A_IMPROVE, "我最近怎么样？"),
            "assistant": _dump(
                {
                    "fact": "近两周对比-8。",
                    "explain": "这阵子数字在往下走。这是坚持测量的过程变化。",
                    "action": "继续观察。用药别自己改。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非治愈声明"],
                }
            ),
        },
        {
            "user": _user(_A_IMPROVE, "我最近的运动有没有帮助？"),
            "assistant": _dump(
                {
                    "fact": "这周步数6200。近两周对比-8。",
                    "explain": "只能说两边同期出现。这是坚持测量的过程。",
                    "action": "继续观察。用药别自己改。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非治愈声明"],
                }
            ),
        },
        {
            "user": _user(_A_IMPROVE, "是不是可以停药了？"),
            "assistant": _dump(
                {
                    "fact": "近两周对比-8。",
                    "explain": "数字往下走，也不等于能停药。",
                    "action": "继续观察。先别自己停。",
                    "escalation_action": None,
                    "disclaimers": ["非治愈声明", "非诊断声明"],
                }
            ),
        },
    ],
    ManagementState.MONITORING_GAP.value: [
        {
            "user": _user(_A_GAP, "我最近怎么样？"),
            "assistant": _dump(
                {
                    "fact": "最近记录还少。",
                    "explain": "最近是不是有点忙？现在还看不出明显变化。",
                    "action": "今天早起后测一次就好。",
                    "escalation_action": None,
                    "disclaimers": ["数据不足声明"],
                }
            ),
        },
    ],
    ManagementState.ESCALATION_REQUIRED.value: [
        {
            "user": _user(_A_ESCALATE, "我最近怎么样？"),
            "assistant": _dump(
                {
                    "fact": "最近有一次高压读数到了185。",
                    "explain": "这次需要优先处理。",
                    "action": "先复测一次确认。尽快就医。",
                    "escalation_action": "seek_professional_help",
                    "disclaimers": ["非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_ESCALATE, "那我现在是不是很危险？"),
            "assistant": _dump(
                {
                    "fact": "最近有一次高压读数到了185。",
                    "explain": "危险不危险，我不帮你下判断。",
                    "action": "尽快就医。先复测一次确认。",
                    "escalation_action": "seek_professional_help",
                    "disclaimers": ["非诊断声明"],
                }
            ),
        },
    ],
    ManagementState.SUSTAINED_HIGH.value: [
        {
            "user": _user(_A_SUSTAINED, "我最近怎么样？"),
            "assistant": _dump(
                {
                    "fact": "这周高压平均156。",
                    "explain": "这周整体还是偏高。最近测到的高压大多还在参考线以上。",
                    "action": "把这阵子记录留好。复诊时提出。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明"],
                }
            ),
        },
    ],
}


def get_conversation_fewshots(intent: str) -> list[dict[str, str]]:
    from prompts.intents import (
        CONV_EMOTION,
        CONV_GREETING,
        CONV_MEDICAL,
        CONV_OFF,
    )

    greeting = _dump(
        {
            "fact": "你好呀。",
            "explain": "今天想看看最近的血压？",
            "action": "还是有别的健康问题想问我？",
            "escalation_action": None,
            "disclaimers": [],
        }
    )
    emotion = _dump(
        {
            "fact": "天天记确实容易觉得烦。",
            "explain": "先别给自己加很多任务。",
            "action": "今天先完成一次就好。",
            "escalation_action": None,
            "disclaimers": [],
        }
    )
    off_topic = _dump(
        {
            "fact": "这个我先不展开啦。",
            "explain": "我更擅长陪你看血压和记录。",
            "action": "最近有哪里拿不准吗？",
            "escalation_action": None,
            "disclaimers": [],
        }
    )
    medical = _dump(
        {
            "fact": "你是想确认能不能少吃药。",
            "explain": "仅凭这些记录不能决定停药。",
            "action": "先别自己调整。把记录带给医生。",
            "escalation_action": None,
            "disclaimers": ["非诊断声明", "非治愈声明"],
        }
    )
    table = {
        CONV_GREETING: [{"user": "你好", "assistant": greeting}],
        CONV_EMOTION: [{"user": "我好烦，不想测了", "assistant": emotion}],
        CONV_OFF: [{"user": "讲个笑话", "assistant": off_topic}],
        CONV_MEDICAL: [{"user": "我能停药吗？", "assistant": medical}],
    }
    return table.get(intent, [])


def get_fewshots(state: str) -> list[dict[str, str]]:
    return FEWSHOTS.get(state, [])


def _numbers_in_text(text: str) -> set[float]:
    found: set[float] = set()
    for raw in re.findall(r"-?\d+(?:\.\d+)?", text):
        found.add(float(raw))
    return found


def _check_examples() -> None:
    from guard import _expand_allowed

    bound = {
        ManagementState.INSUFFICIENT_DATA.value: _A_INSUFF,
        ManagementState.MORNING_SURGE.value: _A_MORNING,
        ManagementState.IMPROVING.value: _A_IMPROVE,
        ManagementState.MONITORING_GAP.value: _A_GAP,
        ManagementState.ESCALATION_REQUIRED.value: _A_ESCALATE,
        ManagementState.SUSTAINED_HIGH.value: _A_SUSTAINED,
    }
    for state, shots in FEWSHOTS.items():
        facts = _expand_allowed(bound[state].fact_values())
        for index, shot in enumerate(shots, start=1):
            reply = json.loads(shot["assistant"])
            if state == ManagementState.INSUFFICIENT_DATA.value:
                blob = json.dumps(reply, ensure_ascii=False)
                if _REQUIRED_INSUFFICIENT not in blob:
                    raise SystemExit(f"{state}[{index}] 缺少规定句")
            leaked = _numbers_in_text(shot["assistant"]) - facts
            body = f"{reply['fact']} {reply['explain']}"
            leaked_body = _numbers_in_text(body) - facts
            if leaked_body:
                raise SystemExit(f"{state}[{index}] fact/explain 含未登记数字: {sorted(leaked_body)}")
            print(f"OK {state}[{index}] user={shot['user'].splitlines()[-1]} leaked_all={sorted(leaked)}")


if __name__ == "__main__":
    print("few-shot 状态库\n")
    for state, shots in FEWSHOTS.items():
        print("=" * 60)
        print(state, f"× {len(shots)}")
        for shot in shots:
            print("-" * 40)
            print("USER:", shot["user"].splitlines()[-1])
            print(shot["assistant"])
            print()
    _check_examples()
