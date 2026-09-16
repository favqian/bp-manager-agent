"""边界验收：数据不足样本。不是第四名核心患者，不进入 rules.py 三人主流程。"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from rules import OUT_DIR, assess

BOUNDARY_ID = "boundary_insufficient"
BOUNDARY_DIR = Path(__file__).parent / "data" / "boundary"
CSV_PATH = BOUNDARY_DIR / "insufficient_data.csv"
JSON_PATH = OUT_DIR / "boundary_insufficient_assessment.json"
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

# 仅前 3 天早晨各完成 1 次，共 3 次有效测量（< params.SUFFICIENCY.min_valid_30d=7），
# 且近 7 天无测量、最长漏测间隔远大于 7 天。漏测行血压留空，不填 0。
COMPLETED_SLOTS = {
    (0, "morning"): (148, 92, 76, 4100),
    (1, "morning"): (151, 94, 80, 3800),
    (2, "morning"): (149, 91, 78, 3600),
}


def write_boundary_csv() -> Path:
    BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for day_index in range(DAYS):
        day = START + timedelta(days=day_index)
        for slot in ("morning", "evening"):
            vitals = COMPLETED_SLOTS.get((day_index, slot))
            if vitals:
                systolic, diastolic, heart_rate, steps = vitals
                rows.append(
                    {
                        "patient_id": BOUNDARY_ID,
                        "patient_name": "边界样本（非核心患者）",
                        "date": day.isoformat(),
                        "measurement_time": slot,
                        "scheduled": 1,
                        "systolic_bp": systolic,
                        "diastolic_bp": diastolic,
                        "heart_rate": heart_rate,
                        "steps": steps,
                        "completed": 1,
                    }
                )
            else:
                rows.append(
                    {
                        "patient_id": BOUNDARY_ID,
                        "patient_name": "边界样本（非核心患者）",
                        "date": day.isoformat(),
                        "measurement_time": slot,
                        "scheduled": 1,
                        "systolic_bp": "",
                        "diastolic_bp": "",
                        "heart_rate": "",
                        "steps": "",
                        "completed": 0,
                    }
                )
    with CSV_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return CSV_PATH


def main() -> None:
    csv_path = write_boundary_csv()
    result = assess(BOUNDARY_ID, csv_path=csv_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(result.to_json(), encoding="utf-8")
    print("边界验收样本（非核心患者，不进入三人主流程）")
    print(f"CSV  : {csv_path}")
    print(f"JSON : {JSON_PATH}")
    print()
    print(result.to_json())
    print()
    print(
        f"验收核对: sufficient={result.sufficient}  "
        f"state={result.state}  "
        f"reason={result.sufficient_reason!r}  "
        f"trend.direction={result.trend.get('direction')}"
    )
    if not result.sufficient and result.state == "INSUFFICIENT_DATA":
        print("通过：数据不足 → 不推断趋势。")
    else:
        raise SystemExit("未通过：边界样本应满足 sufficient=false 且 state=INSUFFICIENT_DATA")


if __name__ == "__main__":
    main()
