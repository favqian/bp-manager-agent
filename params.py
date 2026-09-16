# 演示参数（Demo Parameters）
# 以下阈值仅用于构造 MVP 演示场景，使三名虚拟患者能稳定落入不同管理状态，
# 不代表临床诊断标准或产品结论。正式产品需依据专业规范与真实数据分布重新校准。

"""集中存放 Demo 阈值。state.py 读 STATE.*，rules.py 读 PATTERN.*，禁止在业务代码里写死裸数字。"""

from dataclasses import dataclass, fields

DISCLAIMER = (
    "以下阈值仅用于构造 MVP 演示场景，使三名虚拟患者能稳定落入不同管理状态，"
    "不代表临床诊断标准或产品结论。正式产品需依据专业规范与真实数据分布重新校准。"
)


@dataclass(frozen=True)
class SufficiencyParams:
    min_valid_30d: int = 7
    # 次。近 30 天最少有效测量次数，低于此值则数据不足以判断趋势。
    max_gap_days: int = 7
    # 天。允许的最大连续漏测间隔，超过则视为数据不连续。
    min_valid_7d: int = 0
    # 次。近 7 天最少有效测量次数；Demo 设为 0，避免短窗误判为数据不足。


@dataclass(frozen=True)
class RiskParams:
    high_sys_mean_7d: int = 160
    # mmHg。近 7 日平均收缩压达到此值，风险描述记为 high。
    crisis_sys: int = 180
    # mmHg。单次收缩压达到此值，触发危机级关注。
    crisis_dia: int = 110
    # mmHg。单次舒张压达到此值，触发危机级关注。
    moderate_sys_low: int = 140
    # mmHg。近窗平均收缩压达到此值（且未到 high），风险描述记为 moderate。
    high_sd: int = 12
    # mmHg。近 7 日收缩压标准差达到此值，视为波动偏大。
    low_target_rate: float = 0.7
    # 比例（0–1）。30 日读数落在参考线内的比例低于此值，视为达标率偏低。
    target_dia: int = 90
    # mmHg。Demo 当日达标参考线的舒张压；与 moderate_sys_low（140）组成 140/90 可视化参考，非个体化治疗目标。


@dataclass(frozen=True)
class PatternParams:
    min_paired_days: int = 7
    # 天。至少需要这么多「早+晚成对」天数，才判断晨晚差异模式。
    morning_evening_delta: int = 10
    # mmHg。早晨均值高于晚上达到此差值，视为存在晨晚差异。
    # 与 STATE.morning_surge_delta 语义相同，rules.py 读本组。


@dataclass(frozen=True)
class TrendParams:
    min_valid_for_trend: int = 14
    # 次。判断趋势所需的最少有效测量次数。
    improving_delta: int = 5
    # mmHg。对比窗收缩压下降达到此值，视为改善方向。


@dataclass(frozen=True)
class StateParams:
    """状态机触发阈值，必须可校准；state.py 只读本组，不允许写死 0.3 / 3 / 10。"""

    monitoring_gap_rate: float = 0.3
    # 比例（0–1）。近窗依从率低于此值，进入 MONITORING_GAP。
    monitoring_gap_days: int = 3
    # 天。距上次测量超过此天数，进入 MONITORING_GAP。
    morning_surge_delta: int = 10
    # mmHg。与 PATTERN.morning_evening_delta 复用同一语义，state.py 读本组。


@dataclass(frozen=True)
class WindowParams:
    days_30: int = 30
    # 天。长期统计窗口。
    days_7: int = 7
    # 天。近窗统计窗口。
    days_14: int = 14
    # 天。趋势对比所用半窗。


@dataclass(frozen=True)
class TextParams:
    max_sentence_chars: int = 20
    # 字。AI 单句建议不超过此长度（Demo 文案约束）。
    max_total_chars: int = 180
    # 字。AI 洞察全文建议不超过此长度。
    max_signal_chars: int = 25
    # 字。signals 单条事实点上限。


SUFFICIENCY = SufficiencyParams()
RISK = RiskParams()
PATTERN = PatternParams()
TREND = TrendParams()
STATE = StateParams()
WINDOW = WindowParams()
TEXT = TextParams()

_GROUPS = {
    "SUFFICIENCY": SUFFICIENCY,
    "RISK": RISK,
    "PATTERN": PATTERN,
    "TREND": TREND,
    "STATE": STATE,
    "WINDOW": WINDOW,
    "TEXT": TEXT,
}

_FIELD_NOTES = {
    "SUFFICIENCY.min_valid_30d": "次；近30天最少有效测量次数",
    "SUFFICIENCY.max_gap_days": "天；允许的最大连续漏测间隔",
    "SUFFICIENCY.min_valid_7d": "次；近7天最少有效测量次数",
    "RISK.high_sys_mean_7d": "mmHg；近7日平均收缩压 high 阈值",
    "RISK.crisis_sys": "mmHg；单次收缩压危机阈值",
    "RISK.crisis_dia": "mmHg；单次舒张压危机阈值",
    "RISK.moderate_sys_low": "mmHg；moderate 风险描述下限",
    "RISK.high_sd": "mmHg；近7日收缩压标准差偏大阈值",
    "RISK.low_target_rate": "比例；30日参考线内达标率偏低阈值",
    "RISK.target_dia": "mmHg；Demo 当日达标参考线舒张压",
    "WINDOW.days_30": "天；长期统计窗口",
    "WINDOW.days_7": "天；近窗统计窗口",
    "WINDOW.days_14": "天；趋势对比半窗",
    "TEXT.max_signal_chars": "字；signals 单条事实点上限",
    "PATTERN.min_paired_days": "天；判断晨晚差异所需最少成对天数",
    "PATTERN.morning_evening_delta": "mmHg；晨晚差值阈值（rules.py 读取）",
    "TREND.min_valid_for_trend": "次；判断趋势所需最少有效测量",
    "TREND.improving_delta": "mmHg；对比窗收缩压下降达到此值视为改善",
    "STATE.monitoring_gap_rate": "比例；近窗依从率低于此值进入监测中断",
    "STATE.monitoring_gap_days": "天；距上次测量超过此天数进入监测中断",
    "STATE.morning_surge_delta": "mmHg；晨晚差值阈值（state.py 读取，与 PATTERN 同语义）",
    "TEXT.max_sentence_chars": "字；AI 单句建议上限",
    "TEXT.max_total_chars": "字；AI 洞察全文建议上限",
}


def describe() -> None:
    """打印全部 Demo 参数，并附带免责说明。"""
    print("演示参数（Demo Parameters）")
    print(DISCLAIMER)
    print()
    for group_name, group in _GROUPS.items():
        print(f"[{group_name}]")
        for item in fields(group):
            key = f"{group_name}.{item.name}"
            note = _FIELD_NOTES.get(key, "")
            print(f"  {item.name} = {getattr(group, item.name)}    # {note}")
        print()
