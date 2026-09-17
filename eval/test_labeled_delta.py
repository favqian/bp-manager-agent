"""Evaluator 自测：delta 只在明确差值陈述时校验。不调模型。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import (
    _blob,
    _expand_allowed,
    count_labeled_fact_errors,
    extract_delta_claims,
)


class _StubAssessment:
    bp = {"sys_mean_7d": 144.6, "target_rate_30d": 0.0}
    adherence = {"rate_7d": 1.0}
    pattern = {
        "morning_mean": 152.0,
        "evening_mean": 137.0,
        "delta": 15.0,
    }

    def fact_values(self) -> set[float]:
        return {152.0, 137.0, 15.0, 144.6, 0.0, 1.0}


def _check(text: str) -> tuple[list[float], int]:
    assessment = _StubAssessment()
    blob = _blob({"fact": text, "explain": "", "action": ""})
    allowed = _expand_allowed(assessment.fact_values())
    payload = {
        "bp": assessment.bp,
        "adherence": assessment.adherence,
        "pattern": assessment.pattern,
    }
    return extract_delta_claims(blob), count_labeled_fact_errors(blob, payload, allowed)


def main() -> None:
    cases = [
        (1, "把晨晚差记录下来。", False, True),
        (2, "注意晨晚差异。", False, True),
        (3, "晨间152、晚间137，把晨晚差记录下来。", False, True),
        (4, "晨晚差15。", True, True),
        (5, "早晚相差15。", True, True),
        (6, "差值是15。", True, True),
        (7, "晨晚差20。", True, False),
        (8, "早晚相差10。", True, False),
    ]
    failed: list[str] = []
    for cid, text, should_claim, should_pass in cases:
        claims, errors = _check(text)
        claimed = len(claims) > 0
        passed = errors == 0
        ok = claimed == should_claim and passed == should_pass
        mark = "PASS" if ok else "FAIL"
        print(
            f"{mark} {cid}: {text!r}  claims={claims}  "
            f"errors={errors}  expect_claim={should_claim}  expect_pass={should_pass}"
        )
        if not ok:
            failed.append(str(cid))
    if failed:
        raise SystemExit(f"FAIL: {', '.join(failed)}")
    print("PASS: 1-8 全部符合预期")


if __name__ == "__main__":
    main()
