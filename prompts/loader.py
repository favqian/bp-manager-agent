"""组装发给模型的消息：system → 判读结果 → 策略卡 → 示例 → 历史 → 用户消息。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROMPTS_DIR = Path(__file__).parent
SYSTEM_PATH = PROMPTS_DIR / "system.md"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def load_system() -> str:
    text = SYSTEM_PATH.read_text(encoding="utf-8")
    return _HTML_COMMENT.sub("", text).strip()


def _as_json_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if hasattr(payload, "to_json"):
        return payload.to_json()
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fewshot_messages(fewshots: list | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if not fewshots:
        return messages
    for item in fewshots:
        if "role" in item and "content" in item:
            messages.append({"role": item["role"], "content": item["content"]})
            continue
        if "user" in item:
            messages.append({"role": "user", "content": item["user"]})
        if "assistant" in item:
            messages.append({"role": "assistant", "content": item["assistant"]})
    return messages


def build_messages(
    assessment_json: Any,
    playbook: Any,
    fewshots: list | None,
    user_msg: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """顺序：【system】→【判读结果JSON】→【当前状态策略卡】→【示例】→【历史】→【用户消息】。"""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": load_system()},
        {
            "role": "user",
            "content": "【判读结果】\n" + _as_json_text(assessment_json),
        },
        {
            "role": "user",
            "content": "【当前状态策略卡】\n" + _as_json_text(playbook),
        },
    ]

    fewshot_msgs = _fewshot_messages(fewshots)
    if fewshot_msgs:
        blocks = ["【示例】下面是表达风格示例，不要照抄数字。"]
        for msg in fewshot_msgs:
            blocks.append(f"[{msg['role']}]\n{msg['content']}")
        messages.append({"role": "user", "content": "\n\n".join(blocks)})

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_msg})
    return messages


def debug_print_messages(messages: list[dict[str, str]]) -> None:
    """打印最终发给模型的完整内容，用于检查注入是否正确。"""
    print("=" * 72)
    print("debug_print_messages：最终发给模型的完整 prompt")
    print("=" * 72)
    for index, message in enumerate(messages, start=1):
        print(f"\n----- [{index}] role={message['role']} -----")
        print(message["content"])
    print("\n" + "=" * 72)
    print(f"共 {len(messages)} 条消息")


if __name__ == "__main__":
    from rules import assess
    from state import apply_state, get_playbook
    from prompts.fewshots import get_fewshots

    assessment = apply_state(assess("patient_001"))
    playbook = get_playbook(assessment.state)
    messages = build_messages(
        assessment_json=assessment.to_json(),
        playbook=playbook,
        fewshots=get_fewshots(assessment.state),
        user_msg="我最近怎么样？",
        history=[],
    )
    debug_print_messages(messages)
