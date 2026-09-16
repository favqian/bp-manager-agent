"""边界验收：数据不足样本。不进入 rules.py 三人主流程，不是核心患者。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rules import assess

CSV_PATH = ROOT / "data" / "boundary" / "insufficient_data.csv"
PATIENT_ID = "boundary_insufficient"


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"找不到边界样本 CSV: {CSV_PATH}")

    result = assess(PATIENT_ID, csv_path=CSV_PATH)
    print(f"patient_id         = {result.patient_id}")
    print(f"sufficient         = {result.sufficient}")
    print(f"sufficient_reason  = {result.sufficient_reason}")
    print(f"state              = {result.state}")

    if result.sufficient is False and result.state == "INSUFFICIENT_DATA":
        print("PASS")
        return
    raise SystemExit("FAIL: 期望 sufficient=false 且 state=INSUFFICIENT_DATA")


if __name__ == "__main__":
    main()
