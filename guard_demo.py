"""Guard 规则验收。只用于验证，不进 Agent 主流程，不调用模型。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import Assessment, ManagementState
from guard import validate

STABLE = ManagementState.STABLE_MAINTAIN.value
INSUFFICIENT = ManagementState.INSUFFICIENT_DATA.value
ESCALATE = ManagementState.ESCALATION_REQUIRED.value


def _assessment(**overrides) -> Assessment:
    """手工评估对象：只服务本脚本，不走 rules.py。"""
    base = dict(
        patient_id="guard_demo",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={"days": 30, "valid_measurements": 40, "expected": 60, "coverage_rate": 0.77},
        adherence={
            "rate_30d": 0.77,
            "rate_7d": 0.8,
            "max_gap_days": 1,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 150.0,
            "sys_sd_7d": 4.0,
            "dia_mean_7d": 88.0,
            "sys_mean_30d": 150.0,
            "target_rate_30d": 0.5,
            "max_single": {"sys": 155, "dia": 92, "date": "2026-01-10"},
        },
        pattern={
            "morning_mean": 151.0,
            "evening_mean": 149.0,
            "delta": 2.0,
            "stable_delta": False,
            "paired_days": 10,
        },
        trend={"slope_per_week": 0.2, "direction": "stable", "compare_14d": 1.0},
        activity={"steps_mean_7d": 5000, "steps_delta": 100, "hr_mean_7d": 76},
        risk_level="low",
        state=STABLE,
        escalation_required=False,
        escalation_action=None,
        signals=["近窗均值150"],
        required_disclaimers=["非诊断声明"],
        needs_human=False,
        human_route=None,
    )
    base.update(overrides)
    return Assessment(**base)


def _reply(fact: str, explain: str, action: str, escalation_action=None) -> dict:
    return {
        "fact": fact,
        "explain": explain,
        "action": action,
        "escalation_action": escalation_action,
        "disclaimers": ["非诊断声明"],
    }


CASES = [
    {
        "id": "①",
        "title": "编造判读结果里没有的血压数值",
        "expect_block": True,
        "assessment": _assessment(),
        "reply": _reply(
            "您的平均血压 168。",
            "先看这一组数字。",
            "今天测一次就行。",
        ),
    },
    {
        "id": "②",
        "title": "出现违禁词「可以停药了」",
        "expect_block": True,
        "assessment": _assessment(),
        "reply": _reply(
            "近窗均值150。",
            "可以停药了。",
            "今天测一次就行。",
        ),
    },
    {
        "id": "③",
        "title": "sufficient=false 却没说数据不足",
        "expect_block": True,
        "assessment": _assessment(
            sufficient=False,
            sufficient_reason="近30天有效测量不足",
            state=INSUFFICIENT,
        ),
        "reply": _reply(
            "记录还比较少。",
            "我先不判断趋势。",
            "今天测一次就行。",
        ),
    },
    {
        "id": "④",
        "title": "action 里塞了 3 个任务",
        "expect_block": True,
        "assessment": _assessment(),
        "reply": _reply(
            "近窗均值150。",
            "先把动作收一收。",
            "今天测一次。早起后再测。复诊时带上。",
        ),
    },
    {
        "id": "⑤",
        "title": "输出不是 JSON，而是整段自然语言",
        "expect_block": True,
        "assessment": _assessment(),
        "reply": "您最近血压控制得还不错，继续保持就好。",
    },
    {
        "id": "⑥",
        "title": "需要升级却未给出升级动作",
        "expect_block": True,
        "assessment": _assessment(
            state=ESCALATE,
            escalation_required=True,
            escalation_action="seek_professional_help",
            needs_human=True,
            human_route="seek_professional_help",
            bp={
                "sys_mean_7d": 150.0,
                "sys_sd_7d": 4.0,
                "dia_mean_7d": 88.0,
                "sys_mean_30d": 150.0,
                "target_rate_30d": 0.5,
                "max_single": {"sys": 185, "dia": 102, "date": "2026-01-17"},
            },
        ),
        "reply": _reply(
            "有一次读数185。",
            "先说这次读数。",
            "先复测一次确认。",
            escalation_action=None,
        ),
    },
    {
        "id": "⑦",
        "title": "应当放行：今天测一次就行（次数，非事实值）",
        "expect_block": False,
        "assessment": _assessment(),
        "reply": _reply(
            "已记录3次。",
            "次数不是血压读数。",
            "今天测一次就行。",
        ),
    },
    {
        "id": "⑧",
        "title": "应当放行：近 30 天依从率 77%（在 fact_values 内）",
        "expect_block": False,
        "assessment": _assessment(),
        "reply": _reply(
            "近 30 天依从率 77%。",
            "我只引用已有比例。",
            "继续按点测。",
        ),
    },
]


def main() -> None:
    print("guard_demo：逐条调用 guard.validate，不进主流程、不调用模型")
    print(f"样例 ⑧ 所用 fact_values = {sorted(_assessment().fact_values())}")
    print()
    failures: list[str] = []
    for case in CASES:
        ok, reasons = validate(case["reply"], case["assessment"])
        blocked = not ok
        expect_block = case["expect_block"]
        passed = blocked is expect_block
        mark = "PASS" if passed else "FAIL"
        verdict = "拦截" if blocked else "放行"
        expect = "拦截" if expect_block else "放行"
        print("=" * 64)
        print(f"{case['id']} {case['title']}")
        print(f"  期望: {expect}")
        print(f"  判定: {verdict}  [{mark}]")
        print(f"  原因: {reasons if reasons else '[]'}")
        if not passed:
            failures.append(
                f"{case['id']} 期望{expect}，实际{verdict}，原因={reasons}"
            )

    print()
    print("=" * 64)
    if failures:
        print("FAIL：")
        for item in failures:
            print(" ", item)
        raise SystemExit(1)
    print("PASS：①—⑥ 全部拦截，⑦⑧ 全部放行。")


if __name__ == "__main__":
    main()
