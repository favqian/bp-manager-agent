"""判读结果 JSON 合同：规则层与 AI 层的唯一接口。本文件只定结构，不含计算逻辑。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import params


class ManagementState(str, Enum):
    """管理状态（Agent 行为路由依据）。ESCALATION_REQUIRED 表示触发专业关注路径，不是「该用户属于高风险等级」。"""

    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"
    # 需要专业关注 → PRD S2 + 人工介入节点
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    # 数据不足 → PRD 设计原则1
    MONITORING_GAP = "MONITORING_GAP"
    # 监测中断 → PRD S1
    SUSTAINED_HIGH = "SUSTAINED_HIGH"
    # 持续偏高 → PRD S2
    MORNING_SURGE = "MORNING_SURGE"
    # 晨晚差异 → PRD S2 + 患者B
    IMPROVING = "IMPROVING"
    # 持续改善 → PRD S3 + 患者C
    STABLE_MAINTAIN = "STABLE_MAINTAIN"
    # 平稳维持


# 事实类数值路径：血压、心率、百分比、趋势变化值。日期 / 天数 / 序号 / 次数不计入。
_FACT_PATHS = (
    ("window", "coverage_rate"),
    ("adherence", "rate_30d"),
    ("adherence", "rate_7d"),
    ("bp", "sys_mean_7d"),
    ("bp", "sys_sd_7d"),
    ("bp", "dia_mean_7d"),
    ("bp", "sys_mean_30d"),
    ("bp", "target_rate_30d"),
    ("bp", "max_single", "sys"),
    ("bp", "max_single", "dia"),
    ("pattern", "morning_mean"),
    ("pattern", "evening_mean"),
    ("pattern", "delta"),
    ("pattern", "stable_delta"),
    ("trend", "slope_per_week"),
    ("trend", "compare_14d"),
    ("activity", "steps_mean_7d"),
    ("activity", "steps_delta"),
    ("activity", "hr_mean_7d"),
)


def _dig(data: dict, path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


@dataclass
class Assessment:
    """一次判读的完整结果。规则层产出本对象，AI 层只许引用其中的事实，不得改写数字。"""

    patient_id: str
    as_of: str
    # 判读基准日期，例如 2026-01-30

    sufficient: bool
    # 数据是否足以判断趋势
    sufficient_reason: str = ""
    # 不足时的一句原因，可为空

    window: dict = field(default_factory=dict)
    # {days, valid_measurements, expected, coverage_rate}
    adherence: dict = field(default_factory=dict)
    # {rate_30d, rate_7d, max_gap_days, last_measure_date, days_since_last}
    bp: dict = field(default_factory=dict)
    # {sys_mean_7d, sys_sd_7d, dia_mean_7d, sys_mean_30d, target_rate_30d, max_single:{sys, dia, date}}
    pattern: dict = field(default_factory=dict)
    # {morning_mean, evening_mean, delta, stable_delta, paired_days}
    trend: dict = field(default_factory=dict)
    # {slope_per_week, direction, compare_14d}
    activity: dict = field(default_factory=dict)
    # {steps_mean_7d, steps_delta, hr_mean_7d}

    risk_level: str = "unknown"
    # high / moderate / low / unknown
    # 描述性指标：描述当前数据表现，不直接驱动 Agent 行为
    state: str | None = None
    # 最终管理状态由 state.py decide_state() 回填，rules.py 不写死

    escalation_required: bool = False
    # 是否需要专业人员进一步关注/处理（结构化字段）
    escalation_action: str | None = None
    # 升级动作类型：contact_doctor / seek_professional_help

    signals: list[str] = field(default_factory=list)
    # 供 AI 引用的事实点，每条 ≤25 字且必须含数字
    required_disclaimers: list[str] = field(default_factory=list)

    needs_human: bool = False
    # 与 escalation_required 同义，保留以兼容规则层命名
    human_route: str | None = None

    def to_json(self) -> str:
        """中文可读 JSON。"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def fact_values(self) -> set[float]:
        """只返回事实类数值，供后续校验 AI 文案是否编造数字。"""
        payload = asdict(self)
        values: set[float] = set()
        for path in _FACT_PATHS:
            raw = _dig(payload, path)
            if raw is None or isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)):
                values.add(float(raw))
        return values


def example_patient_001() -> Assessment:
    """手写示例：只展示结构，数字不是规则层计算结果。"""
    return Assessment(
        patient_id="patient_001",
        as_of="2026-01-30",
        sufficient=True,
        sufficient_reason="",
        window={
            "days": 30,
            "valid_measurements": 46,
            "expected": 60,
            "coverage_rate": 0.767,
        },
        adherence={
            "rate_30d": 0.767,
            "rate_7d": 0.286,
            "max_gap_days": 4,
            "last_measure_date": "2026-01-30",
            "days_since_last": 0,
        },
        bp={
            "sys_mean_7d": 155.0,
            "sys_sd_7d": 4.2,
            "dia_mean_7d": 96.0,
            "sys_mean_30d": 152.7,
            "target_rate_30d": 0.11,
            "max_single": {"sys": 168, "dia": 98, "date": "2026-01-04"},
        },
        pattern={
            "morning_mean": 153.0,
            "evening_mean": 152.0,
            "delta": 1.0,
            "stable_delta": False,
            "paired_days": 21,
        },
        trend={
            "slope_per_week": 0.4,
            "direction": "flat",
            "compare_14d": 1.2,
        },
        activity={
            "steps_mean_7d": 2600,
            "steps_delta": -1800,
            "hr_mean_7d": 88,
        },
        risk_level="moderate",
        state=ManagementState.MONITORING_GAP.value,
        escalation_required=False,
        escalation_action=None,
        signals=[
            "近7日依从率28.6%",
            "30日依从率76.7%",
            "近7日收缩压均值155",
            "距上次测量0天",
        ],
        required_disclaimers=[
            "本结果基于家庭自测模拟数据，不做疾病诊断，不改变药物方案，不代替医生。",
        ],
        needs_human=False,
        human_route=None,
    )


if __name__ == "__main__":
    assessment = example_patient_001()
    print("=== Assessment JSON ===")
    print(assessment.to_json())
    print()
    print("=== fact_values() ===")
    print(sorted(assessment.fact_values()))
    print()
    print("=== params.describe() ===")
    params.describe()
