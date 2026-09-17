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
from prompts.scenes import get_scene, push_user_msg

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
TEMPERATURE = 0.3
MAX_TOKENS = 500
THINKING = {"type": "disabled"}
HISTORY_LIMIT = 6
MAX_ATTEMPTS = 2
_LAST_RESPONSE_MODEL: str | None = None
_LAST_TURN_TRACE: dict[str, Any] = {
    "attempts": [],
    "degraded": False,
    "fallback_used": False,
    "final_reply": None,
}


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
    """唯一的模型调用点。Non-Thinking：thinking.type=disabled，temperature 才生效。"""
    global _LAST_RESPONSE_MODEL
    response = _client().chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=messages,
        extra_body={"thinking": dict(THINKING)},
    )
    _LAST_RESPONSE_MODEL = getattr(response, "model", None)
    content = response.choices[0].message.content
    return content or ""


def describe_runtime() -> dict[str, Any]:
    """不打印 key。供 debug/test 确认实际命中的模型。"""
    return {
        "requested_model": MODEL,
        "response_model": _LAST_RESPONSE_MODEL,
        "base_url": BASE_URL,
        "thinking": THINKING.get("type"),
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }


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


def _public_trace_reply(reply: dict) -> dict[str, Any]:
    return {
        "fact": reply.get("fact"),
        "explain": reply.get("explain"),
        "action": reply.get("action"),
        "escalation_action": reply.get("escalation_action"),
        "disclaimers": reply.get("disclaimers") or [],
    }


def _reset_turn_trace() -> None:
    global _LAST_TURN_TRACE
    _LAST_TURN_TRACE = {
        "attempts": [],
        "degraded": False,
        "fallback_used": False,
        "final_reply": None,
    }


def take_turn_trace() -> dict[str, Any]:
    """评测读取本轮 attempts；不进入产品回复，不包含 API Key。"""
    global _LAST_TURN_TRACE
    snapshot = {
        "attempts": list(_LAST_TURN_TRACE.get("attempts") or []),
        "degraded": bool(_LAST_TURN_TRACE.get("degraded")),
        "fallback_used": bool(_LAST_TURN_TRACE.get("fallback_used")),
        "final_reply": _LAST_TURN_TRACE.get("final_reply"),
    }
    _reset_turn_trace()
    return snapshot


def _record_attempt(
    attempt: int,
    raw_model_reply: str,
    guard_ok: bool,
    guard_reasons: list[str],
) -> None:
    _LAST_TURN_TRACE["attempts"].append(
        {
            "attempt": attempt,
            "raw_model_reply": raw_model_reply,
            "guard_ok": guard_ok,
            "guard_reasons": list(guard_reasons),
        }
    )


def _annotate(reply: dict, degraded: bool, reasons: list[str]) -> dict:
    result = dict(reply)
    result["degraded"] = degraded
    result["reasons"] = list(reasons)
    return result


def generate_push(assessment: Any, playbook: Any, scene: str) -> dict:
    """场景推送：页面只传 scene，Prompt 由场景层组装。"""
    if get_scene(scene) is None:
        raise KeyError(f"未知场景: {scene}")
    return chat(
        assessment=assessment,
        playbook=playbook,
        user_msg=push_user_msg(scene),
        history=[],
        scene=scene,
    )


def chat(
    assessment: Any,
    playbook: Any,
    user_msg: str,
    history: list[dict[str, str]] | None = None,
    scene: str | None = None,
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
        scene=scene,
    )

    _reset_turn_trace()
    last_reasons = ["G1 JSON 结构不完整"]
    last_raw = ""
    attempt_messages = list(messages)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        last_raw = _call_model(attempt_messages)
        reply = _parse_reply(last_raw)
        if reply is None:
            last_reasons = ["G1 JSON 结构不完整：无法解析模型输出"]
            _record_attempt(attempt, last_raw, False, last_reasons)
        else:
            ok, last_reasons = guard.validate(reply, assessment)
            _record_attempt(attempt, last_raw, ok, [] if ok else last_reasons)
            if ok:
                result = _annotate(reply, False, [])
                _LAST_TURN_TRACE["degraded"] = False
                _LAST_TURN_TRACE["fallback_used"] = False
                _LAST_TURN_TRACE["final_reply"] = _public_trace_reply(result)
                return result
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

    fallback_reply = guard.fallback(
        assessment,
        playbook,
        scene=scene,
        user_query=user_msg,
        history=recent,
    )
    result = _annotate(fallback_reply, True, last_reasons)
    _LAST_TURN_TRACE["degraded"] = True
    _LAST_TURN_TRACE["fallback_used"] = True
    _LAST_TURN_TRACE["final_reply"] = _public_trace_reply(result)
    return result
