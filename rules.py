"""读取患者 CSV，按 params 阈值计算 contract.Assessment。漏测不填 0、不插值、不伪造。"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

import params
from contract import Assessment, ManagementState

BASE_DIR = Path(__file__).parent
CSV_DIR = BASE_DIR / "data" / "patients"
OUT_DIR = BASE_DIR / "data" / "assess"

CSV_DONE = 1  # CSV 编码：已完成测量，不是临床阈值
CSV_PLANNED = 1  # CSV 编码：计划测量时段
SLOT_MORNING = "morning"
SLOT_EVENING = "evening"
LINEAR_DEGREE = 1  # 简单线性回归，不是临床阈值
MMHG_DIGITS = 1  # JSON 血压小数位，不是临床阈值
RATE_DIGITS = 3  # JSON 比例小数位，不是临床阈值
MIN_POINTS = 2  # 标准差 / 斜率至少需要的点数

DEMO_PATIENTS = ("patient_001", "patient_002", "patient_003")

_DISCLAIMER = "本结果基于家庭自测模拟数据，不做疾病诊断，不改变药物方案，不代替医生。"


def _has_digit(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _round(value: float | None, digits: int = MMHG_DIGITS) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return round(float(value), digits)


def _pct_text(rate: float | None) -> str | None:
    if rate is None:
        return None
    return f"{rate:.0%}"


def _mean(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return float(series.mean())


def _std(series: pd.Series) -> float | None:
    if len(series) < MIN_POINTS:
        return None
    return float(series.std(ddof=LINEAR_DEGREE))


def _in_last_n_days(dates: pd.Series, as_of: pd.Timestamp, days: int) -> pd.Series:
    delta = (as_of - dates).dt.days
    return (delta >= 0) & (delta < days)


def load_patient_csv(patient_id: str) -> pd.DataFrame:
    path = CSV_DIR / f"{patient_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"找不到患者 CSV: {path}")
    df = pd.read_csv(path)
    required = {
        "patient_id",
        "date",
        "measurement_time",
        "scheduled",
        "systolic_bp",
        "diastolic_bp",
        "heart_rate",
        "steps",
        "completed",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} 缺少字段: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"])
    df["systolic_bp"] = pd.to_numeric(df["systolic_bp"], errors="coerce")
    df["diastolic_bp"] = pd.to_numeric(df["diastolic_bp"], errors="coerce")
    df["heart_rate"] = pd.to_numeric(df["heart_rate"], errors="coerce")
    df["steps"] = pd.to_numeric(df["steps"], errors="coerce")
    return df


def _valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """只保留真正完成且血压非空的行。漏测保持空值，不填 0。"""
    return df[
        (df["completed"] == CSV_DONE)
        & df["systolic_bp"].notna()
        & df["diastolic_bp"].notna()
    ].copy()


def _max_gap_days(all_dates: pd.Series, valid_dates: pd.Series, as_of: pd.Timestamp) -> int:
    start = all_dates.min()
    calendar = pd.date_range(start, as_of, freq="D")
    measured = set(valid_dates.dt.normalize())
    longest = 0
    current = 0
    for day in calendar:
        if day.normalize() in measured:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _daily_target_rate(valid: pd.DataFrame) -> float | None:
    if valid.empty:
        return None
    daily = valid.groupby(valid["date"].dt.normalize()).agg(
        sys=("systolic_bp", "mean"),
        dia=("diastolic_bp", "mean"),
    )
    hit = (daily["sys"] < params.RISK.moderate_sys_low) & (
        daily["dia"] < params.RISK.target_dia
    )
    return float(hit.mean())


def _pattern(valid: pd.DataFrame) -> dict:
    empty = {
        "morning_mean": None,
        "evening_mean": None,
        "delta": None,
        "stable_delta": False,
        "paired_days": 0,
    }
    if valid.empty:
        return empty

    pivot = valid.pivot_table(
        index=valid["date"].dt.normalize(),
        columns="measurement_time",
        values="systolic_bp",
        aggfunc="mean",
    )
    if SLOT_MORNING not in pivot.columns or SLOT_EVENING not in pivot.columns:
        return empty

    paired = pivot[[SLOT_MORNING, SLOT_EVENING]].dropna()
    paired_days = int(len(paired))
    if paired_days < params.PATTERN.min_paired_days:
        return {
            "morning_mean": None,
            "evening_mean": None,
            "delta": None,
            "stable_delta": False,
            "paired_days": paired_days,
        }

    morning_mean = float(paired[SLOT_MORNING].mean())
    evening_mean = float(paired[SLOT_EVENING].mean())
    delta = morning_mean - evening_mean
    return {
        "morning_mean": _round(morning_mean),
        "evening_mean": _round(evening_mean),
        "delta": _round(delta),
        "stable_delta": delta >= params.PATTERN.morning_evening_delta,
        "paired_days": paired_days,
    }


def _trend(valid: pd.DataFrame, as_of: pd.Timestamp, sufficient: bool) -> dict:
    unknown = {"slope_per_week": None, "direction": "unknown", "compare_14d": None}
    if valid.empty:
        return unknown

    recent_mask = _in_last_n_days(valid["date"], as_of, params.WINDOW.days_14)
    prev_mask = _in_last_n_days(valid["date"], as_of, params.WINDOW.days_14 * 2) & ~recent_mask
    recent_mean = _mean(valid.loc[recent_mask, "systolic_bp"])
    prev_mean = _mean(valid.loc[prev_mask, "systolic_bp"])
    compare_14d = None
    if recent_mean is not None and prev_mean is not None:
        compare_14d = recent_mean - prev_mean

    slope_per_week = None
    if len(valid) >= MIN_POINTS:
        day_index = (valid["date"] - valid["date"].min()).dt.days.astype(float)
        if day_index.nunique() >= MIN_POINTS:
            daily_slope = float(np.polyfit(day_index, valid["systolic_bp"], LINEAR_DEGREE)[0])
            slope_per_week = daily_slope * params.WINDOW.days_7

    if (not sufficient) or len(valid) < params.TREND.min_valid_for_trend:
        direction = "unknown"
    elif (
        compare_14d is not None
        and compare_14d <= -params.TREND.improving_delta
        and slope_per_week is not None
        and slope_per_week < 0
    ):
        direction = "improving"
    elif compare_14d is not None and compare_14d >= params.TREND.improving_delta:
        direction = "worsening"
    else:
        direction = "stable"

    return {
        "slope_per_week": _round(slope_per_week),
        "direction": direction,
        "compare_14d": _round(compare_14d),
    }


def _activity(valid: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    last7 = valid[_in_last_n_days(valid["date"], as_of, params.WINDOW.days_7)]
    prev7 = valid[
        _in_last_n_days(valid["date"], as_of, params.WINDOW.days_7 * 2)
        & ~_in_last_n_days(valid["date"], as_of, params.WINDOW.days_7)
    ]
    steps_7 = _mean(last7["steps"].dropna())
    steps_prev = _mean(prev7["steps"].dropna())
    steps_delta = None
    if steps_7 is not None and steps_prev is not None:
        steps_delta = steps_7 - steps_prev
    return {
        "steps_mean_7d": None if steps_7 is None else int(round(steps_7)),
        "steps_delta": None if steps_delta is None else int(round(steps_delta)),
        "hr_mean_7d": None if last7.empty else int(round(float(last7["heart_rate"].mean()))),
    }


def _sufficient(valid_30d: int, valid_7d: int, max_gap_days: int) -> tuple[bool, str]:
    if valid_30d < params.SUFFICIENCY.min_valid_30d:
        return False, f"近{params.WINDOW.days_30}天有效测量不足"
    if max_gap_days > params.SUFFICIENCY.max_gap_days:
        return False, f"最长漏测间隔{max_gap_days}天"
    if valid_7d <= params.SUFFICIENCY.min_valid_7d:
        return False, f"近{params.WINDOW.days_7}天无有效测量"
    return True, ""


def _risk_level(
    sufficient: bool,
    sys_mean_7d: float | None,
    sys_sd_7d: float | None,
    target_rate_30d: float | None,
    crisis: bool,
) -> str:
    if not sufficient:
        return "unknown"
    if crisis or (
        sys_mean_7d is not None and sys_mean_7d >= params.RISK.high_sys_mean_7d
    ):
        return "high"
    if sys_mean_7d is not None and (
        params.RISK.moderate_sys_low <= sys_mean_7d < params.RISK.high_sys_mean_7d
    ):
        return "moderate"
    if sys_sd_7d is not None and sys_sd_7d > params.RISK.high_sd:
        return "moderate"
    if (
        sys_mean_7d is not None
        and sys_mean_7d < params.RISK.moderate_sys_low
        and target_rate_30d is not None
        and target_rate_30d > params.RISK.low_target_rate
    ):
        return "low"
    return "moderate"


def _resolve_state(
    sufficient: bool,
    rate_7d: float | None,
    days_since_last: int | None,
    stable_delta: bool,
    direction: str,
    sys_mean_7d: float | None,
    crisis: bool,
) -> str:
    if not sufficient:
        return ManagementState.INSUFFICIENT_DATA.value
    if rate_7d is not None and rate_7d < params.STATE.monitoring_gap_rate:
        return ManagementState.MONITORING_GAP.value
    if days_since_last is not None and days_since_last > params.STATE.monitoring_gap_days:
        return ManagementState.MONITORING_GAP.value
    if stable_delta:
        return ManagementState.MORNING_SURGE.value
    if direction == "improving":
        return ManagementState.IMPROVING.value
    if sys_mean_7d is not None and sys_mean_7d >= params.RISK.moderate_sys_low:
        return ManagementState.SUSTAINED_HIGH.value
    if crisis:
        return ManagementState.ESCALATION_REQUIRED.value
    return ManagementState.STABLE_MAINTAIN.value


def _add_signal(signals: list[str], text: str) -> None:
    if not text or not _has_digit(text):
        return
    if len(text) > params.TEXT.max_signal_chars:
        return
    signals.append(text)


def _build_signals(
    *,
    sufficient: bool,
    rate_30d: float | None,
    rate_7d: float | None,
    valid_7d: int,
    days_since_last: int | None,
    sys_mean_7d: float | None,
    target_rate_30d: float | None,
    pattern: dict,
    trend: dict,
    max_single: dict,
) -> list[str]:
    signals: list[str] = []
    if rate_30d is not None and days_since_last:
        _add_signal(
            signals,
            f"{params.WINDOW.days_30}天依从率{_pct_text(rate_30d)}，最近{days_since_last}天未测",
        )
    elif rate_30d is not None and rate_7d is not None:
        _add_signal(
            signals,
            f"{params.WINDOW.days_30}天依从率{_pct_text(rate_30d)}，近{params.WINDOW.days_7}天{_pct_text(rate_7d)}",
        )
    elif rate_30d is not None:
        _add_signal(signals, f"{params.WINDOW.days_30}天依从率{_pct_text(rate_30d)}")

    if sys_mean_7d is None:
        _add_signal(signals, f"近{params.WINDOW.days_7}天有效测量{valid_7d}次")
    else:
        target_txt = _pct_text(target_rate_30d)
        if target_txt:
            _add_signal(
                signals,
                f"近{params.WINDOW.days_7}天均值{sys_mean_7d:.0f}，达标{target_txt}",
            )
        else:
            _add_signal(signals, f"近{params.WINDOW.days_7}天均值{sys_mean_7d:.0f}")

    if pattern["morning_mean"] is not None:
        _add_signal(
            signals,
            (
                f"晨间{pattern['morning_mean']:.0f}、晚间{pattern['evening_mean']:.0f}，"
                f"差{pattern['delta']:.0f}"
            ),
        )

    if sufficient and trend["compare_14d"] is not None:
        _add_signal(signals, f"近{params.WINDOW.days_14}天对比{trend['compare_14d']:+.0f}")

    if max_single.get("sys") is not None:
        _add_signal(
            signals,
            f"{params.WINDOW.days_30}天最高收缩压{max_single['sys']:.0f}",
        )

    return signals


def assess(patient_id: str, as_of: str | None = None) -> Assessment:
    df = load_patient_csv(patient_id)
    as_of_ts = pd.Timestamp(as_of) if as_of else df["date"].max()
    df = df[_in_last_n_days(df["date"], as_of_ts, params.WINDOW.days_30)].copy()

    planned = df[df["scheduled"] == CSV_PLANNED]
    valid = _valid_rows(df)
    last7_all = df[_in_last_n_days(df["date"], as_of_ts, params.WINDOW.days_7)]
    last7_valid = valid[_in_last_n_days(valid["date"], as_of_ts, params.WINDOW.days_7)]
    planned_7 = last7_all[last7_all["scheduled"] == CSV_PLANNED]

    expected = int(len(planned))
    valid_30d = int(len(valid))
    expected_7d = int(len(planned_7))
    valid_7d = int(len(last7_valid))

    rate_30d = (valid_30d / expected) if expected else None
    rate_7d = (valid_7d / expected_7d) if expected_7d else None
    max_gap_days = _max_gap_days(df["date"], valid["date"], as_of_ts)

    last_measure = valid["date"].max() if not valid.empty else pd.NaT
    days_since_last = None if pd.isna(last_measure) else int((as_of_ts - last_measure).days)
    last_measure_date = None if pd.isna(last_measure) else last_measure.strftime("%Y-%m-%d")

    sufficient, sufficient_reason = _sufficient(valid_30d, valid_7d, max_gap_days)

    sys_mean_7d = _round(_mean(last7_valid["systolic_bp"]))
    sys_sd_7d = _round(_std(last7_valid["systolic_bp"]))
    dia_mean_7d = _round(_mean(last7_valid["diastolic_bp"]))
    sys_mean_30d = _round(_mean(valid["systolic_bp"]))
    target_rate_30d = _round(_daily_target_rate(valid), digits=RATE_DIGITS)

    max_single = {"sys": None, "dia": None, "date": None}
    if not valid.empty:
        top = valid.loc[valid["systolic_bp"].idxmax()]
        max_single = {
            "sys": int(top["systolic_bp"]),
            "dia": int(top["diastolic_bp"]),
            "date": top["date"].strftime("%Y-%m-%d"),
        }

    crisis = False
    if not valid.empty:
        crisis = bool(
            (valid["systolic_bp"] >= params.RISK.crisis_sys).any()
            or (valid["diastolic_bp"] >= params.RISK.crisis_dia).any()
        )

    pattern = _pattern(valid)
    trend = _trend(valid, as_of_ts, sufficient)
    activity = _activity(valid, as_of_ts)
    risk_level = _risk_level(
        sufficient, sys_mean_7d, sys_sd_7d, target_rate_30d, crisis
    )
    state = _resolve_state(
        sufficient,
        rate_7d,
        days_since_last,
        bool(pattern["stable_delta"]),
        trend["direction"],
        sys_mean_7d,
        crisis,
    )

    if crisis:
        escalation_required = True
        escalation_action = "seek_professional_help"
    else:
        escalation_required = False
        escalation_action = None

    signals = _build_signals(
        sufficient=sufficient,
        rate_30d=rate_30d,
        rate_7d=rate_7d,
        valid_7d=valid_7d,
        days_since_last=days_since_last,
        sys_mean_7d=sys_mean_7d,
        target_rate_30d=target_rate_30d,
        pattern=pattern,
        trend=trend,
        max_single=max_single,
    )

    window_days = int((as_of_ts - df["date"].min()).days + 1) if not df.empty else 0

    return Assessment(
        patient_id=patient_id,
        as_of=as_of_ts.strftime("%Y-%m-%d"),
        sufficient=sufficient,
        sufficient_reason=sufficient_reason,
        window={
            "days": window_days,
            "valid_measurements": valid_30d,
            "expected": expected,
            "coverage_rate": _round(rate_30d, digits=RATE_DIGITS),
        },
        adherence={
            "rate_30d": _round(rate_30d, digits=RATE_DIGITS),
            "rate_7d": _round(rate_7d, digits=RATE_DIGITS),
            "max_gap_days": max_gap_days,
            "last_measure_date": last_measure_date,
            "days_since_last": days_since_last,
        },
        bp={
            "sys_mean_7d": sys_mean_7d,
            "sys_sd_7d": sys_sd_7d,
            "dia_mean_7d": dia_mean_7d,
            "sys_mean_30d": sys_mean_30d,
            "target_rate_30d": target_rate_30d,
            "max_single": max_single,
        },
        pattern=pattern,
        trend=trend,
        activity=activity,
        risk_level=risk_level,
        state=state,
        escalation_required=escalation_required,
        escalation_action=escalation_action,
        signals=signals,
        required_disclaimers=[_DISCLAIMER],
        needs_human=escalation_required,
        human_route=escalation_action,
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for patient_id in DEMO_PATIENTS:
        result = assess(patient_id)
        out_path = OUT_DIR / f"{patient_id}_assessment.json"
        out_path.write_text(result.to_json(), encoding="utf-8")
        print("=" * 60)
        print(patient_id)
        print(result.to_json())
        print(f"已写入 {out_path}")
        rows.append(
            {
                "patient_id": patient_id,
                "sufficient": result.sufficient,
                "state": result.state,
                "risk_level": result.risk_level,
                "rate_30d": result.adherence.get("rate_30d"),
                "sys_mean_7d": result.bp.get("sys_mean_7d"),
                "delta": result.pattern.get("delta"),
                "direction": result.trend.get("direction"),
                "escalation_action": result.escalation_action,
            }
        )

    print("\n" + "=" * 60)
    print("对照表")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
