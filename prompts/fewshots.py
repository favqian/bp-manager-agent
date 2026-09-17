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
                    "fact": f"{_REQUIRED_INSUFFICIENT}。覆盖率 0.05，近窗依从率 0.0。",
                    "explain": "记录还太少，我不敢往下猜是高了还是稳了。先把测量接上，后面才看得清。",
                    "action": "今天顺手测一次就好，测完我们再看。",
                    "escalation_action": None,
                    "disclaimers": ["数据不足声明"],
                }
            ),
        },
        {
            "user": _user(_A_INSUFF, "为什么这几天总是偏高？"),
            "assistant": _dump(
                {
                    "fact": f"{_REQUIRED_INSUFFICIENT}。近窗没有可引用的收缩压均值。",
                    "explain": "这几天是不是偏高，我现在没有足够读数能下这个判断，不能顺着感觉往高处想。",
                    "action": "先补一次测量。有了新读数，我们再一起看。",
                    "escalation_action": None,
                    "disclaimers": ["数据不足声明", "非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_INSUFF, "我是不是要中风了？"),
            "assistant": _dump(
                {
                    "fact": f"{_REQUIRED_INSUFFICIENT}。覆盖率 0.05。",
                    "explain": "中风这种判断我做不了，也不该拿这么少的记录去吓你。现在缺的是测量，不是结论。",
                    "action": "引导咨询医生/继续监测：今天先测一次；要是你特别不放心，把现有记录带去问医生。",
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
                    "fact": "早晨收缩压均值 152，晚上 137，差 15。近窗均值 145。",
                    "explain": "更值得记下的是时段差：早上明显高于晚上。这是观察规律，不是我在解释原因。",
                    "action": "接下来几天照常早晚各记一次，复诊时把这组晨晚数字带给医生看。用药先按医嘱，别自己改时间。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_MORNING, "为什么这几天总是偏高？"),
            "assistant": _dump(
                {
                    "fact": "近窗收缩压均值 145。晨间 152、晚间 137，差 15。",
                    "explain": "看起来不是全天都高，主要是早晨这一截更高。为什么会这样，我不能猜，需要医生结合你的情况看。",
                    "action": "先把早晚读数连续记下，复诊时主动问医生这组差值。服药时间不要自己调。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_MORNING, "我是不是要中风了？"),
            "assistant": _dump(
                {
                    "fact": "晨间 152、晚间 137，差 15。近窗均值 145。",
                    "explain": "我不能根据这些数字判断你会不会中风，也不做那种推测。眼下能说清楚的，只是早上比晚上高。",
                    "action": "引导咨询医生/继续监测：把晨晚对比带去问医生；这几天继续按点测，有不舒服及时就医。",
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
                    "fact": "前后两段收缩压对比 -8，近窗均值 142，周斜率 -4.4。",
                    "explain": "这半个月数字在往下走，说明测量和日常安排你有在坚持。这是过程上的变化，不是宣告已经没事。",
                    "action": "照现在这样测下去就行，药不要自己停。下次复诊把这段对比带上。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非治愈声明"],
                }
            ),
        },
        {
            "user": _user(_A_IMPROVE, "我最近的运动有没有帮助？"),
            "assistant": _dump(
                {
                    "fact": "近窗步数 6200，步数变化 900。收缩压对比 -8，近窗均值 142。",
                    "explain": "活动量和血压下降是同期出现的，我只能说两边一起被观察到了，不能说就是运动把血压带下来的。",
                    "action": "能走的日子继续走，测量也别断。有没有帮助，留给复诊时医生一起看。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明", "非治愈声明"],
                }
            ),
        },
        {
            "user": _user(_A_IMPROVE, "是不是可以停药了？"),
            "assistant": _dump(
                {
                    "fact": "收缩压对比 -8，近窗均值 142。",
                    "explain": "数字在往下走，值得肯定，但不等于可以停药。降压药一般要长期按医嘱吃，能不能减、能不能停，只能医生结合你的情况定，我不能替你做这个决定。",
                    "action": "引导咨询医生/继续监测：先不要自己停；把这段下降记录带去问医生或药师。",
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
                    "fact": "近窗依从率 0.14，近窗收缩压均值 156。",
                    "explain": "不是你不听话，这两天多半是忙忘了。数字还在，就是近窗测得少了点。",
                    "action": "今天早起后测一次就够，测完我们就接着看。",
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
                    "fact": "有一次收缩压读数 185。",
                    "explain": "这件事我想先说清楚：这不是让我跟你细聊趋势的时候，是该让医生看一眼的时候。",
                    "action": "尽快就医。先按平时方法再测一次确认，然后把 185 这次读数带去给医生。",
                    "escalation_action": "seek_professional_help",
                    "disclaimers": ["非诊断声明"],
                }
            ),
        },
        {
            "user": _user(_A_ESCALATE, "那我现在是不是很危险？"),
            "assistant": _dump(
                {
                    "fact": "触发关注的是单次收缩压 185。",
                    "explain": "危险不危险，我不帮你下这个判断，也不往坏处猜。我能明确的是：这次读数需要专业人员接手。",
                    "action": "尽快就医，不要只在这里继续追问。复测一次后联系医生。",
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
                    "fact": "近窗收缩压均值 156，达标比例 0.08。",
                    "explain": "整体看，最近这一段是偏高一些。我不拿你跟别人比，也不猜原因。",
                    "action": "把近窗均值 156 记下来，复诊时直接问医生。这几天照常测。",
                    "escalation_action": None,
                    "disclaimers": ["非因果声明"],
                }
            ),
        },
    ],
}


def get_fewshots(state: str) -> list[dict[str, str]]:
    return FEWSHOTS.get(state, [])


def _numbers_in_text(text: str) -> set[float]:
    found: set[float] = set()
    for raw in re.findall(r"-?\d+(?:\.\d+)?", text):
        found.add(float(raw))
    return found


def _check_examples() -> None:
    bound = {
        ManagementState.INSUFFICIENT_DATA.value: _A_INSUFF,
        ManagementState.MORNING_SURGE.value: _A_MORNING,
        ManagementState.IMPROVING.value: _A_IMPROVE,
        ManagementState.MONITORING_GAP.value: _A_GAP,
        ManagementState.ESCALATION_REQUIRED.value: _A_ESCALATE,
        ManagementState.SUSTAINED_HIGH.value: _A_SUSTAINED,
    }
    for state, shots in FEWSHOTS.items():
        facts = bound[state].fact_values()
        for index, shot in enumerate(shots, start=1):
            reply = json.loads(shot["assistant"])
            if state == ManagementState.INSUFFICIENT_DATA.value:
                blob = json.dumps(reply, ensure_ascii=False)
                if _REQUIRED_INSUFFICIENT not in blob:
                    raise SystemExit(f"{state}[{index}] 缺少规定句")
            leaked = _numbers_in_text(shot["assistant"]) - facts
            # 动作层允许「一次」以外的流程性数字；这里只拦 fact/explain 里的事实数字。
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
