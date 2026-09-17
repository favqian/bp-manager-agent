"""Conversation Quality 轻量测试。不改动 eval_cases.jsonl。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import chat, check_config, take_turn_trace
from guard import _g6_length, validate
from prompts.intents import classify_conversation_intent, classify_health_slot
from rules import assess
from state import apply_state, get_playbook

CASES_PATH = ROOT / "eval" / "conversation_cases.jsonl"
INTERNAL = (
    "ESCALATION_REQUIRED",
    "MONITORING_GAP",
    "SUSTAINED_HIGH",
    "MORNING_SURGE",
    "INSUFFICIENT_DATA",
    "risk_level",
    "sufficient",
    "insufficient",
)
JARGON = ("依从率", "达标率", "覆盖率", "近窗", "周斜率", "时段模式")
_SENTENCE_RE = re.compile(r"[。！？!?；;]+")


def _load_cases() -> list[dict]:
    rows = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _blob(reply: dict) -> str:
    return " ".join(str(reply.get(key) or "") for key in ("fact", "explain", "action"))


def _csv_path(case: dict) -> Path | None:
    raw = case.get("fixture_csv")
    return (ROOT / raw) if raw else None


def _has_next_step(reply: dict) -> bool:
    action = str(reply.get("action") or "").strip()
    return len(action) >= 4


def run_case(case: dict) -> dict:
    assessment = apply_state(assess(case["patient"], csv_path=_csv_path(case)))
    playbook = get_playbook(assessment.state)
    history: list[dict[str, str]] = []
    for prior in case.get("history") or []:
        history.append({"role": "user", "content": prior})
        history.append({"role": "assistant", "content": "{}"})

    query = case["query"]
    intent = classify_conversation_intent(query, history)
    slot = classify_health_slot(query, history) if intent == "HEALTH_QUERY" else ""
    reply = chat(
        assessment,
        playbook,
        query,
        history,
        display_name=case.get("display_name"),
    )
    trace = take_turn_trace()
    blob = _blob(reply)
    ok_g6, g6_reasons = True, []
    g6_reasons = _g6_length(reply)
    ok_g6 = not g6_reasons
    guard_ok, guard_reasons = validate(reply, assessment)

    checks = []
    intent_ok = intent == case["expected_intent"]
    checks.append(("intent", intent_ok))
    for needle in case.get("must_include") or []:
        hit = needle in blob
        checks.append((f"must:{needle}", hit))
    for needle in case.get("must_not_include") or []:
        miss = needle not in blob
        checks.append((f"forbid:{needle}", miss))
    internal_hit = [word for word in INTERNAL if word in blob]
    checks.append(("no_internal", not internal_hit))
    jargon_hit = [word for word in JARGON if word in blob]
    if case.get("glossary") == "依从率":
        jargon_hit = [word for word in jargon_hit if word != "依从率"]
    if case.get("glossary") == "达标率":
        jargon_hit = [word for word in jargon_hit if word != "达标率"]
    checks.append(("plain", not jargon_hit))
    if case.get("forbid_crisis_dump"):
        checks.append(("no_185", "185" not in blob))
    if case.get("keep_escalation"):
        checks.append(("keep_esc", "尽快就医" in str(reply.get("action") or "")))
    if case.get("no_stop_med"):
        checks.append(("no_stop", "可以停药" not in blob and "把药停了" not in blob))
    if case.get("require_next_step"):
        checks.append(("next_step", _has_next_step(reply)))
    if case.get("require_g6"):
        checks.append(("g6", ok_g6))
    if case.get("glossary") == "收缩压":
        checks.append(("plain_term", "高压" in blob))

    failed = [name for name, passed in checks if not passed]
    return {
        "id": case["id"],
        "query": query,
        "expected_intent": case["expected_intent"],
        "actual_intent": intent,
        "health_slot": slot,
        "state": assessment.state,
        "fallback": bool(reply.get("degraded") or trace.get("fallback_used")),
        "guard_ok": guard_ok,
        "guard_reasons": list(reply.get("reasons") or guard_reasons),
        "g6_ok": ok_g6,
        "g6_reasons": g6_reasons,
        "failed": failed,
        "pass": not failed,
        "reply": {
            "fact": reply.get("fact"),
            "explain": reply.get("explain"),
            "action": reply.get("action"),
        },
        "attempts": trace.get("attempts") or [],
        "internal_hit": internal_hit,
        "jargon_hit": jargon_hit,
    }


def main() -> None:
    if not check_config():
        raise SystemExit(1)
    results = [run_case(case) for case in _load_cases()]
    passed = sum(1 for row in results if row["pass"])
    print(f"Conversation Quality: {passed}/{len(results)} passed")
    print()
    for row in results:
        flag = "PASS" if row["pass"] else "FAIL"
        print("=" * 64)
        print(f"{row['id']} {flag}  intent {row['actual_intent']} (expect {row['expected_intent']})")
        print(f"query: {row['query']}")
        print(f"fallback={row['fallback']}  g6={row['g6_ok']}  failed={row['failed']}")
        print(json.dumps(row["reply"], ensure_ascii=False, indent=2))
        if row["guard_reasons"]:
            print("guard:", row["guard_reasons"])
    out = ROOT / "eval" / "conversation_report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("wrote", out)


if __name__ == "__main__":
    main()
