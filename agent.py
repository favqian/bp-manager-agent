"""血压管家 Agent：模型调用只允许出现在本文件。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

import guard
from prompts.fewshots import get_fewshots
from prompts.loader import build_messages

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"
TEMPERATURE = 0.3
MAX_TOKENS = 500
HISTORY_LIMIT = 6
MAX_ATTEMPTS = 2


def _read_key() -> str:
    load_dotenv(ENV_PATH, override=False)
    return (os.getenv("DEEPSEEK_API_KEY") or "").strip()


def check_config() -> bool:
    """只检查 .env 是否存在、key 是否读到且长度 > 0。不打印 key 的任何片段。"""
    key = _read_key() if ENV_PATH.exists() else ""
    if ENV_PATH.exists() and len(key) > 0:
        print("配置正常")
        return True
    print("配置缺失")
    return False


def _client() -> OpenAI:
    key = _read_key()
    if not key:
        raise RuntimeError("配置缺失")
    return OpenAI(api_key=key, base_url=BASE_URL)


def _call_model(messages: list[dict[str, str]]) -> str:
    """唯一的模型调用点。"""
    response = _client().chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=messages,
    )
    content = response.choices[0].message.content
    return content or ""


def _parse_reply(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


def _annotate(reply: dict, degraded: bool, reasons: list[str]) -> dict:
    result = dict(reply)
    result["degraded"] = degraded
    result["reasons"] = list(reasons)
    return result


def chat(
    assessment: Any,
    playbook: Any,
    user_msg: str,
    history: list[dict[str, str]] | None = None,
) -> dict:
    """组装 Prompt → 调模型 → guard.validate；失败则重试 1 次，再失败则 fallback。"""
    recent = list(history or [])[-HISTORY_LIMIT:]
    state = getattr(assessment, "state", None)
    messages = build_messages(
        assessment_json=assessment,
        playbook=playbook,
        fewshots=get_fewshots(state) if state else [],
        user_msg=user_msg,
        history=recent,
    )

    last_reasons = ["G1 JSON 结构不完整"]
    last_raw = ""
    attempt_messages = list(messages)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        last_raw = _call_model(attempt_messages)
        reply = _parse_reply(last_raw)
        if reply is None:
            last_reasons = ["G1 JSON 结构不完整：无法解析模型输出"]
        else:
            ok, last_reasons = guard.validate(reply, assessment)
            if ok:
                return _annotate(reply, False, [])
        if attempt < MAX_ATTEMPTS:
            attempt_messages = messages + [
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": (
                        "上次输出未通过校验："
                        + "；".join(last_reasons)
                        + "。请只输出符合 schema 的 JSON，不要编造数字。"
                    ),
                },
            ]

    fallback_reply = guard.fallback(assessment, playbook)
    return _annotate(fallback_reply, True, last_reasons)
