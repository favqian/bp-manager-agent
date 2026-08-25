"""CSV → FHIR 转换管道：将患者血压 CSV 转为标准 FHIR Bundle。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import importlib.metadata as metadata
import pandas as pd
from pydantic import ValidationError

from fhir.resources.R4B.bundle import Bundle, BundleEntry
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.observation import Observation, ObservationComponent
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.quantity import Quantity
from fhir.resources.R4B.reference import Reference

BASE_DIR = Path(__file__).parent
CSV_DIR = BASE_DIR / "data" / "patients"
FHIR_DIR = BASE_DIR / "data" / "fhir"

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
VITAL_SIGNS = "http://terminology.hl7.org/CodeSystem/observation-category"

# Demo 模拟固定测量时刻（非真实患者测量时间）
TIME_MAP = {
    "morning": "08:00:00+08:00",
    "evening": "20:00:00+08:00",
}

CSV_FILES = [
    "patient_001.csv",
    "patient_002.csv",
    "patient_003.csv",
]


@dataclass
class ValidationStats:
    errors: int = 0
    warnings: int = 0
    info: int = 0
    messages: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors += 1
        self.messages.append(f"[ERROR] {message}")

    def add_warning(self, message: str) -> None:
        self.warnings += 1
        self.messages.append(f"[WARNING] {message}")

    def add_info(self, message: str) -> None:
        self.info += 1
        self.messages.append(f"[INFO] {message}")


def print_environment_report() -> None:
    """执行前输出本地 HealthChain / FHIR 环境检查结果。"""
    print("=" * 60)
    print("环境检查报告")
    print("=" * 60)

    hc_version = metadata.version("healthchain")
    fr_version = metadata.version("fhir.resources")
    print(f"1. HealthChain 实际安装版本: {hc_version}")
    print(f"   fhir.resources 实际安装版本: {fr_version}")
    print("5. HealthChain / fhir.resources 使用的 FHIR 版本: R4B")

    print("\n2-4. HealthChain 源码 helper 检查结果:")
    print("   - 目录 healthchain/fhir/ 不存在；实际路径为 healthchain/fhir_resources/")
    print("   - 未找到 create_ 开头的 FHIR 资源 helper")
    print("   - 未找到 validate_resource 函数")
    print("   - ImplementedResourceRegistry 已实现: Patient, Bundle 等，但不包含 Observation")
    print("   - healthchain.fhir_resources.patient.Patient 可用（Pydantic 模型）")
    print("   - healthchain.fhir_resources.bundleresources.Bundle 可用，但 entry 不接受 Observation")
    print("\n   因此 Observation / Bundle 完整组装与验证改用 fhir.resources R4B 标准模型。")
    print("6. validate_resource: HealthChain 无此 API；本管道使用 fhir.resources + Pydantic 校验。")
    print("=" * 60)
    print()


def csv_patient_id_to_fhir_id(patient_id: str) -> str:
    """FHIR id 不允许下划线，将 patient_001 映射为 patient-001。"""
    return patient_id.replace("_", "-")


def build_effective_datetime(date_value: str, measurement_time: str) -> str:
    if measurement_time not in TIME_MAP:
        raise ValueError(f"未知 measurement_time: {measurement_time!r}，仅支持 morning / evening")
    return f"{date_value}T{TIME_MAP[measurement_time]}"


def build_patient_resource(patient_id: str, patient_name: str) -> Patient:
    fhir_id = csv_patient_id_to_fhir_id(patient_id)
    return Patient(
        id=fhir_id,
        identifier=[
            Identifier(
                system="urn:bp-manager:patient-id",
                value=patient_id,
            )
        ],
        name=[HumanName(text=patient_name)],
    )


def build_blood_pressure_observation(
    obs_id: str,
    patient_id: str,
    effective_dt: str,
    systolic: int,
    diastolic: int,
) -> Observation:
    patient_ref = f"Patient/{csv_patient_id_to_fhir_id(patient_id)}"
    return Observation(
        id=obs_id,
        status="final",
        category=[
            CodeableConcept(
                coding=[
                    Coding(
                        system=VITAL_SIGNS,
                        code="vital-signs",
                        display="Vital Signs",
                    )
                ]
            )
        ],
        code=CodeableConcept(
            coding=[
                Coding(
                    system=LOINC,
                    code="85354-9",
                    display="Blood pressure panel",
                )
            ]
        ),
        subject=Reference(reference=patient_ref),
        effectiveDateTime=effective_dt,
        component=[
            ObservationComponent(
                code=CodeableConcept(
                    coding=[
                        Coding(
                            system=LOINC,
                            code="8480-6",
                            display="Systolic blood pressure",
                        )
                    ]
                ),
                valueQuantity=Quantity(
                    value=systolic,
                    unit="mmHg",
                    system=UCUM,
                    code="mm[Hg]",
                ),
            ),
            ObservationComponent(
                code=CodeableConcept(
                    coding=[
                        Coding(
                            system=LOINC,
                            code="8462-4",
                            display="Diastolic blood pressure",
                        )
                    ]
                ),
                valueQuantity=Quantity(
                    value=diastolic,
                    unit="mmHg",
                    system=UCUM,
                    code="mm[Hg]",
                ),
            ),
        ],
    )


def build_heart_rate_observation(
    obs_id: str,
    patient_id: str,
    effective_dt: str,
    heart_rate: int,
) -> Observation:
    patient_ref = f"Patient/{csv_patient_id_to_fhir_id(patient_id)}"
    return Observation(
        id=obs_id,
        status="final",
        category=[
            CodeableConcept(
                coding=[
                    Coding(
                        system=VITAL_SIGNS,
                        code="vital-signs",
                        display="Vital Signs",
                    )
                ]
            )
        ],
        code=CodeableConcept(
            coding=[
                Coding(
                    system=LOINC,
                    code="8867-4",
                    display="Heart rate",
                )
            ]
        ),
        subject=Reference(reference=patient_ref),
        effectiveDateTime=effective_dt,
        valueQuantity=Quantity(
            value=heart_rate,
            unit="beats/min",
            system=UCUM,
            code="/min",
        ),
    )


def validate_fhir_resource(resource: Patient | Observation | Bundle, label: str) -> ValidationStats:
    """使用 fhir.resources（Pydantic）验证 FHIR 资源。"""
    stats = ValidationStats()
    try:
        resource.model_validate(resource.model_dump(mode="json"))
        stats.add_info(f"{label} 通过 Pydantic/FHIR 结构验证")
    except ValidationError as exc:
        for issue in exc.errors():
            stats.add_error(f"{label}: {issue['loc']} -> {issue['msg']}")
    return stats


def merge_stats(target: ValidationStats, source: ValidationStats) -> None:
    target.errors += source.errors
    target.warnings += source.warnings
    target.info += source.info
    target.messages.extend(source.messages)


def load_and_validate_csv(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 CSV 文件: {csv_path}")

    df = pd.read_csv(csv_path)
    required_columns = {
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
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path.name} 缺少字段: {sorted(missing)}")

    return df


def convert_csv_to_bundle(csv_path: Path) -> tuple[Bundle, dict]:
    df = load_and_validate_csv(csv_path)
    patient_id = str(df["patient_id"].iloc[0])
    patient_name = str(df["patient_name"].iloc[0])

    patient = build_patient_resource(patient_id, patient_name)
    entries: list[BundleEntry] = [BundleEntry(resource=patient)]

    bp_count = 0
    hr_count = 0
    skipped = 0

    for index, row in df.iterrows():
        if int(row["scheduled"]) != 1:
            continue

        if int(row["completed"]) != 1:
            skipped += 1
            continue

        measurement_time = str(row["measurement_time"])
        date_value = str(row["date"])
        effective_dt = build_effective_datetime(date_value, measurement_time)

        systolic = row["systolic_bp"]
        diastolic = row["diastolic_bp"]
        heart_rate = row["heart_rate"]

        if pd.isna(systolic) or pd.isna(diastolic) or pd.isna(heart_rate):
            raise ValueError(
                f"{csv_path.name} 第 {index + 2} 行 completed=1 但血压/心率为空，数据不合法"
            )

        systolic_int = int(systolic)
        diastolic_int = int(diastolic)
        heart_rate_int = int(heart_rate)

        if not (60 <= systolic_int <= 250):
            raise ValueError(f"{csv_path.name} 第 {index + 2} 行收缩压超出合理范围: {systolic_int}")
        if not (40 <= diastolic_int <= 150):
            raise ValueError(f"{csv_path.name} 第 {index + 2} 行舒张压超出合理范围: {diastolic_int}")
        if not (40 <= heart_rate_int <= 200):
            raise ValueError(f"{csv_path.name} 第 {index + 2} 行心率超出合理范围: {heart_rate_int}")

        slot_suffix = measurement_time[:1]
        bp_id = f"bp-{csv_patient_id_to_fhir_id(patient_id)}-{index}-{slot_suffix}"
        hr_id = f"hr-{csv_patient_id_to_fhir_id(patient_id)}-{index}-{slot_suffix}"

        bp_obs = build_blood_pressure_observation(
            bp_id,
            patient_id,
            effective_dt,
            systolic_int,
            diastolic_int,
        )
        hr_obs = build_heart_rate_observation(
            hr_id,
            patient_id,
            effective_dt,
            heart_rate_int,
        )

        entries.append(BundleEntry(resource=bp_obs))
        entries.append(BundleEntry(resource=hr_obs))
        bp_count += 1
        hr_count += 1

    bundle = Bundle(
        type="collection",
        entry=entries,
    )

    summary = {
        "csv_file": csv_path.name,
        "patient_id": patient_id,
        "fhir_patient_id": csv_patient_id_to_fhir_id(patient_id),
        "completed_rows": bp_count,
        "bp_observations": bp_count,
        "hr_observations": hr_count,
        "skipped_missed": skipped,
        "total_entries": len(entries),
    }
    return bundle, summary


def save_bundle(bundle: Bundle, output_path: Path) -> None:
    FHIR_DIR.mkdir(parents=True, exist_ok=True)
    payload = bundle.model_dump(mode="json", exclude_none=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_validation_block(title: str, stats: ValidationStats) -> None:
    print(f"{title} validation:")
    print(f"  error = {stats.errors}")
    print(f"  warning = {stats.warnings}")
    print(f"  info = {stats.info}")
    for message in stats.messages:
        if message.startswith("[WARNING]") or message.startswith("[ERROR]"):
            print(f"  - {message}")


def run_pipeline() -> int:
    print_environment_report()

    all_patient_stats = ValidationStats()
    all_observation_stats = ValidationStats()
    all_bundle_stats = ValidationStats()
    summaries: list[dict] = []

    for csv_name in CSV_FILES:
        csv_path = CSV_DIR / csv_name
        bundle_id = csv_name.replace(".csv", "")
        output_path = FHIR_DIR / f"{bundle_id}_bundle.json"

        print(f"正在转换 {csv_name} ...")
        bundle, summary = convert_csv_to_bundle(csv_path)
        save_bundle(bundle, output_path)
        summaries.append(summary)
        print(f"  已写入 {output_path}")

        patient_resource = bundle.entry[0].resource
        patient_stats = validate_fhir_resource(patient_resource, f"Patient/{summary['fhir_patient_id']}")
        merge_stats(all_patient_stats, patient_stats)

        for entry in bundle.entry[1:]:
            obs_stats = validate_fhir_resource(
                entry.resource,
                f"Observation/{entry.resource.id}",
            )
            merge_stats(all_observation_stats, obs_stats)

        bundle_stats = validate_fhir_resource(bundle, f"Bundle/{bundle_id}")
        merge_stats(all_bundle_stats, bundle_stats)

    print("\n" + "=" * 60)
    print("FHIR 验证结果")
    print("=" * 60)
    print_validation_block("Patient", all_patient_stats)
    print_validation_block("Observation", all_observation_stats)
    print_validation_block("Bundle", all_bundle_stats)

    print("\n" + "=" * 60)
    print("最终测试总结")
    print("=" * 60)
    for summary in summaries:
        print(
            f"- {summary['csv_file']}: completed={summary['completed_rows']}, "
            f"BP Obs={summary['bp_observations']}, HR Obs={summary['hr_observations']}, "
            f"漏测跳过={summary['skipped_missed']}, Bundle 总条目={summary['total_entries']}"
        )

    total_errors = (
        all_patient_stats.errors
        + all_observation_stats.errors
        + all_bundle_stats.errors
    )
    if total_errors == 0:
        print("\n全部验证通过：error = 0")
    else:
        print(f"\n验证失败：共 {total_errors} 个 error")
        return 1

    if all_patient_stats.warnings + all_observation_stats.warnings + all_bundle_stats.warnings:
        print("\n存在 warning，请查看上方明细。")
    else:
        print("\n无 warning。")

    return 0


if __name__ == "__main__":
    sys.exit(run_pipeline())
