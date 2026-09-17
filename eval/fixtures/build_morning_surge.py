"""评测夹具：构造 MORNING_SURGE。不进入三人主流程，不改核心患者 CSV。"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rules import assess
from state import apply_state, decide_state

FIXTURE_ID = "eval_morning_surge"
OUT_PATH = Path(__file__).resolve().parent / "eval_morning_surge.csv"
START = date(2026, 1, 1)
DAYS = 30
COLUMNS = [
    "patient_id",
    "patient_name",
    "date",
    "measurement_time",
    "scheduled",
    "systolic_bp",
    "diastolic_bp",
    "heart_rate",
    "steps",
    "completed",
]


def write_csv() -> Path:
    """全窗成对测量：早晨约 152、晚上约 137，无危机读数，近窗依从完整。"""
    rows = []
    for day_index in range(DAYS):
        day = START + timedelta(days=day_index)
        wobble = day_index % 3 - 1
        slots = {
            "morning": (152 + wobble, 92, 72, 5200),
            "evening": (137 + wobble, 84, 70, 4800),
        }
        for slot, (sys_bp, dia_bp, hr, steps) in slots.items():
            rows.append(
                {
                    "patient_id": FIXTURE_ID,
                    "patient_name": "评测夹具（晨晚差异）",
                    "date": day.isoformat(),
                    "measurement_time": slot,
                    "scheduled": 1,
                    "systolic_bp": sys_bp,
                    "diastolic_bp": dia_bp,
                    "heart_rate": hr,
                    "steps": steps,
                    "completed": 1,
                }
            )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return OUT_PATH


def main() -> None:
    path = write_csv()
    assessment = apply_state(assess(FIXTURE_ID, csv_path=path))
    print(f"CSV   : {path}")
    print(f"state : {assessment.state}")
    print(f"route : {decide_state(assessment)}")
    print(f"delta : {assessment.pattern}")
    print(f"esc   : {assessment.escalation_required} {assessment.escalation_action}")
    print(f"suff  : {assessment.sufficient} rate_7d={assessment.adherence.get('rate_7d')}")
    if assessment.state != "MORNING_SURGE":
        raise SystemExit(f"FAIL: 夹具应路由到 MORNING_SURGE，实际 {assessment.state}")
    print("PASS：夹具为 MORNING_SURGE，未改 live routing / 核心患者 CSV。")


if __name__ == "__main__":
    main()
