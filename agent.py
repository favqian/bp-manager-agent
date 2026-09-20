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
from prompts.fewshots import get_conversation_fewshots, get_fewshots
from prompts.intents import CONV_HEALTH, classify_conversation_intent
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
_LAST_CONFIG_SOURCE: str = "none"


def _read_streamlit_secret(name: str) -> str:
    """读取 Streamlit Secrets；非 Streamlit 环境或未配置时返回空串。不打印值。"""
    try:
        import streamlit as st  # noqa: WPS433 — 仅在需要时探测 Cloud/本地 secrets

        raw = st.secrets.get(name, "")
    except Exception:
        return ""
    if raw is None:
        return ""
    return str(raw).strip()


def _read_key() -> str:
    """唯一读 key 入口。兼容本地 .env 与 Streamlit Secrets / 进程环境变量。"""
    global _LAST_CONFIG_SOURCE
    load_dotenv(ENV_PATH, override=False)
    env_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if env_key:
        # Cloud 常把 Secrets 注入进程环境；本地则多由 .env 载入 getenv。
        _LAST_CONFIG_SOURCE = "dotenv" if ENV_PATH.exists() else "process_env"
        return env_key
    secret_key = _read_streamlit_secret("DEEPSEEK_API_KEY")
    if secret_key:
        _LAST_CONFIG_SOURCE = "streamlit_secrets"
        return secret_key
    _LAST_CONFIG_SOURCE = "none"
    return ""


def check_config() -> bool:
    """以能否读到非空 DEEPSEEK_API_KEY 为准，不以 .env 文件是否存在为准。"""
    return len(_read_key()) > 0


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
    """模型运行状态唯一事实源（不含 API Key 或其片段）。"""
    configured = check_config()
    attempts = list(_LAST_TURN_TRACE.get("attempts") or [])
    fallback_used = bool(_LAST_TURN_TRACE.get("fallback_used"))
    degraded = bool(_LAST_TURN_TRACE.get("degraded"))
    model_call_succeeded = any(
        bool(row.get("guard_ok")) for row in attempts
    ) and not fallback_used
    return {
        "api_key_configured": configured,
        "config_source": _LAST_CONFIG_SOURCE if configured else "none",
        "requested_model": MODEL,
        "response_model": _LAST_RESPONSE_MODEL,
        "base_url": BASE_URL,
        "thinking": THINKING.get("type"),
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "model_call_succeeded": model_call_succeeded,
        "fallback_used": fallback_used,
        "degraded": degraded,
        "attempts": len(attempts),
        "attempt_details": [
            {
                "attempt": row.get("attempt"),
                "guard_ok": bool(row.get("guard_ok")),
                "guard_reasons": list(row.get("guard_reasons") or []),
            }
            for row in attempts
        ],
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


def _ensure_playbook_disclaimers(reply: dict, playbook: Any) -> dict:
    """模型过 Guard 后仍补齐策略卡声明，不改 fact/explain/action，不改 G1–G6。"""
    result = dict(reply)
    required = list((playbook or {}).get("disclaimers") or [])
    current = result.get("disclaimers") or []
    if isinstance(current, str):
        current = [current]
    else:
        current = list(current)
    for item in required:
        if item and item not in current:
            current.append(item)
    result["disclaimers"] = current
    return result


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
    display_name: str | None = None,
    action_plan_brief: str | None = None,
) -> dict:
    """组装 Prompt → 调模型 → guard.validate；失败则重试 1 次，再失败则 fallback。"""
    recent = list(history or [])[-HISTORY_LIMIT:]
    state = getattr(assessment, "state", None)
    conv = classify_conversation_intent(user_msg, recent)
    if scene:
        fewshots = get_fewshots(state) if state else []
    elif conv != CONV_HEALTH:
        fewshots = get_conversation_fewshots(conv)
    else:
        fewshots = get_fewshots(state) if state else []
    messages = build_messages(
        assessment_json=assessment,
        playbook=playbook,
        fewshots=fewshots,
        user_msg=user_msg,
        history=recent,
        scene=scene,
        display_name=display_name,
        action_plan_brief=action_plan_brief,
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
                reply = _ensure_playbook_disclaimers(reply, playbook)
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
        display_name=display_name,
    )
    result = _annotate(fallback_reply, True, last_reasons)
    _LAST_TURN_TRACE["degraded"] = True
    _LAST_TURN_TRACE["fallback_used"] = True
    _LAST_TURN_TRACE["final_reply"] = _public_trace_reply(result)
    return result
