"""生成 3 名虚拟高血压患者的 30 天家庭血压监测数据。"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).parent / "data" / "patients"
START_DATE = date(2026, 1, 1)
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


def _dates() -> list[date]:
    return [START_DATE + timedelta(days=i) for i in range(DAYS)]


def _clamp(value: float, low: float, high: float) -> int:
    return int(round(max(low, min(high, value))))


def _gen_vitals(steps_range: tuple[int, int]) -> tuple[int, int]:
    heart_rate = random.randint(60, 100)
    steps = random.randint(steps_range[0], steps_range[1])
    return heart_rate, steps


def _gen_bp(
    systolic_target: float,
    systolic_std: float,
    diastolic_center: float,
    diastolic_spread: tuple[int, int] = (88, 98),
) -> tuple[int, int]:
    systolic = _clamp(random.gauss(systolic_target, systolic_std), 115, 185)
    diastolic = _clamp(
        diastolic_center + (systolic - systolic_target) * 0.35 + random.gauss(0, 2.5),
        diastolic_spread[0],
        diastolic_spread[1],
    )
    return systolic, diastolic


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _empty_row(
    patient_id: str,
    patient_name: str,
    day: date,
    measurement_time: str,
) -> dict:
    return {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "date": day.isoformat(),
        "measurement_time": measurement_time,
        "scheduled": 1,
        "systolic_bp": "",
        "diastolic_bp": "",
        "heart_rate": "",
        "steps": "",
        "completed": 0,
    }


def _completed_row(
    patient_id: str,
    patient_name: str,
    day: date,
    measurement_time: str,
    systolic: int,
    diastolic: int,
    heart_rate: int,
    steps: int,
) -> dict:
    return {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "date": day.isoformat(),
        "measurement_time": measurement_time,
        "scheduled": 1,
        "systolic_bp": systolic,
        "diastolic_bp": diastolic,
        "heart_rate": heart_rate,
        "steps": steps,
        "completed": 1,
    }


def generate_patient_001() -> list[dict]:
    """张阿姨：未控制期 + 依从性下降。"""
    rows: list[dict] = []
    completed_late = {
        (22, "morning"),
        (23, "evening"),
        (26, "morning"),
        (30, "evening"),
    }

    for day_index, day in enumerate(_dates()):
        for slot in ("morning", "evening"):
            day_number = day_index + 1
            if day_number <= 21 or (day_number, slot) in completed_late:
                steps_range = (2500, 7000) if day_number >= 22 else (2000, 9000)
                systolic, diastolic = _gen_bp(152, 10, 93)
                heart_rate, steps = _gen_vitals(steps_range)
                rows.append(
                    _completed_row(
                        "patient_001",
                        "张阿姨",
                        day,
                        slot,
                        systolic,
                        diastolic,
                        heart_rate,
                        steps,
                    )
                )
            else:
                rows.append(_empty_row("patient_001", "张阿姨", day, slot))

    return rows


def generate_patient_002() -> list[dict]:
    """李叔叔：波动期 + 明显晨峰。"""
    rows: list[dict] = []
    slots: list[tuple[date, str]] = []
    for day in _dates():
        slots.append((day, "morning"))
        slots.append((day, "evening"))

    missed_indices = sorted(random.sample(range(len(slots)), 9))
    missed = {slots[index] for index in missed_indices}

    for day, slot in slots:
        if (day, slot) in missed:
            rows.append(_empty_row("patient_002", "李叔叔", day, slot))
            continue

        if slot == "morning":
            systolic, diastolic = _gen_bp(155, 14, 96, (90, 102))
        else:
            systolic, diastolic = _gen_bp(135, 14, 86, (78, 95))

        heart_rate, steps = _gen_vitals((2000, 9000))
        rows.append(
            _completed_row(
                "patient_002",
                "李叔叔",
                day,
                slot,
                systolic,
                diastolic,
                heart_rate,
                steps,
            )
        )

    return rows


def generate_patient_003() -> list[dict]:
    """王先生：改善期 + 干预后逐渐下降。"""
    rows: list[dict] = []

    for day_index, day in enumerate(_dates()):
        day_number = day_index + 1
        if day_number <= 14:
            systolic_target = 156 + random.gauss(0, 4)
            diastolic_center = 94 + random.gauss(0, 2)
            steps_range = (3500, 5500)
        else:
            progress = (day_number - 15) / 15
            systolic_target = 156 - progress * 18 + random.gauss(0, 2.5)
            diastolic_center = 94 - progress * 10 + random.gauss(0, 1.5)
            steps_range = (5000, 8000)

        systolic = _clamp(systolic_target, 125, 175)
        diastolic = _clamp(
            diastolic_center + (systolic - systolic_target) * 0.25,
            75,
            100,
        )
        heart_rate, steps = _gen_vitals(steps_range)
        rows.append(
            _completed_row(
                "patient_003",
                "王先生",
                day,
                "morning",
                systolic,
                diastolic,
                heart_rate,
                steps,
            )
        )

    return rows


def _print_summary(label: str, rows: list[dict]) -> None:
    scheduled = sum(row["scheduled"] == 1 for row in rows)
    completed = sum(row["completed"] == 1 for row in rows)
    systolic_values = [row["systolic_bp"] for row in rows if row["completed"] == 1]
    diastolic_values = [row["diastolic_bp"] for row in rows if row["completed"] == 1]
    avg_sys = sum(systolic_values) / len(systolic_values)
    avg_dia = sum(diastolic_values) / len(diastolic_values)
    print(
        f"{label}: 依从率 {completed}/{scheduled} = {completed / scheduled:.1%}, "
        f"平均收缩压 {avg_sys:.1f}, 平均舒张压 {avg_dia:.1f}"
    )


def main() -> None:
    datasets = {
        "patient_001.csv": generate_patient_001(),
        "patient_002.csv": generate_patient_002(),
        "patient_003.csv": generate_patient_003(),
    }

    for filename, rows in datasets.items():
        output_path = DATA_DIR / filename
        _write_csv(output_path, rows)
        _print_summary(filename, rows)
        print(f"已写入 {output_path}")


if __name__ == "__main__":
    main()
