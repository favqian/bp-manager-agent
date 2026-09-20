from pathlib import Path

import html
import json

import altair as alt
import pandas as pd
import streamlit as st

import actions
import agent
import guard
from contract import Assessment
from prompts.fewshots import get_conversation_fewshots, get_fewshots
from prompts.intents import CONV_HEALTH, classify_conversation_intent
from prompts.loader import build_messages
from prompts.scenes import SCENES, push_user_msg
from rules import assess
from state import apply_state, get_playbook

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "patients"
FHIR_DIR = ROOT / "data" / "fhir"
EVAL_DIR = ROOT / "eval"

PATIENTS = {
    "张阿姨（58岁）": {
        "file": "patient_001.csv",
        "patient_id": "patient_001",
        "age": 58,
        "short_name": "张阿姨",
    },
    "李叔叔（63岁）": {
        "file": "patient_002.csv",
        "patient_id": "patient_002",
        "age": 63,
        "short_name": "李叔叔",
    },
    "王先生（45岁）": {
        "file": "patient_003.csv",
        "patient_id": "patient_003",
        "age": 45,
        "short_name": "王先生",
    },
}

STATE_LABELS = {
    "ESCALATION_REQUIRED": "需要专业关注",
    "INSUFFICIENT_DATA": "数据不足",
    "MONITORING_GAP": "监测中断",
    "SUSTAINED_HIGH": "持续偏高",
    "MORNING_SURGE": "晨晚差异",
    "IMPROVING": "持续改善",
    "STABLE_MAINTAIN": "平稳维持",
}

WEEK_ACTION = {
    "ESCALATION_REQUIRED": "先复测一次，尽快让医生看",
    "INSUFFICIENT_DATA": "今天先测一次",
    "MONITORING_GAP": "今天早起后测一次",
    "MORNING_SURGE": "把早晚记录留下来，复诊时提出",
    "SUSTAINED_HIGH": "把最近记录留好，复诊时提出",
    "IMPROVING": "继续测量，观察变化",
    "STABLE_MAINTAIN": "保持现有测量习惯",
}

SCENE_USER_LABELS = {
    "S1": "测量提醒",
    "S2": "异常提醒",
    "S3": "本周总结",
}

ESCALATION_NL = {
    "contact_doctor": "建议尽快联系医生",
    "seek_professional_help": "建议尽快就医",
}

SLOT_HOUR = {"morning": 8, "evening": 20}
SLOT_LABEL = {"morning": "早晨", "evening": "晚上"}


@st.cache_data
def load_patient_data(filename: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / filename)
    df["date"] = pd.to_datetime(df["date"])
    df["systolic_bp"] = pd.to_numeric(df["systolic_bp"], errors="coerce")
    df["diastolic_bp"] = pd.to_numeric(df["diastolic_bp"], errors="coerce")
    df["plot_time"] = df["date"] + pd.to_timedelta(
        df["measurement_time"].map(SLOT_HOUR),
        unit="h",
    )
    missing = (
        (df["completed"] != 1)
        | df["systolic_bp"].isna()
        | df["diastolic_bp"].isna()
    )
    df.loc[missing, ["systolic_bp", "diastolic_bp"]] = pd.NA
    df["slot"] = df["measurement_time"].map(SLOT_LABEL)
    return df.sort_values("plot_time")


@st.cache_data(show_spinner=False)
def cached_assessment(patient_id: str, nonce: int) -> dict:
    assessment = apply_state(assess(patient_id))
    return json.loads(assessment.to_json())


@st.cache_data(show_spinner=False)
def load_fhir_preview(patient_id: str, limit: int = 2000) -> str:
    path = FHIR_DIR / f"{patient_id}_bundle.json"
    if not path.exists():
        return f"未找到 {path.name}"
    return path.read_text(encoding="utf-8")[:limit]


@st.cache_data(show_spinner=False)
def load_eval_summary() -> str:
    files = list(EVAL_DIR.glob("report*.md"))
    if not files:
        return "暂无评测报告。"
    latest = max(files, key=lambda path: path.stat().st_mtime)
    head = "\n".join(latest.read_text(encoding="utf-8").splitlines()[:36])
    return f"{latest.name}\n\n{head}"


def api_configured() -> bool:
    """与 agent 真实读 key 逻辑同源；不缓存，避免误报被锁死。"""
    return agent.check_config()


def _segmented(plot_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """漏测记为空值后分段，折线在缺口处断开，不插值。"""
    work = plot_df[["plot_time", value_col, "date", "slot"]].copy()
    work["gap"] = work[value_col].isna()
    work["segment"] = work["gap"].cumsum()
    return work.loc[~work["gap"]]


def build_bp_chart(plot_df: pd.DataFrame) -> alt.Chart:
    """真实模拟数据；视觉弱化，不抢过 AI Coach / Action。"""
    axis = alt.Axis(
        format="%m-%d",
        labelColor="#9CA3AF",
        titleColor="#9CA3AF",
        gridColor="#EEF0F4",
        domainColor="#E5E7EB",
        tickColor="#E5E7EB",
    )
    y_axis = alt.Axis(
        labelColor="#9CA3AF",
        titleColor="#9CA3AF",
        gridColor="#EEF0F4",
        domainColor="#E5E7EB",
        tickColor="#E5E7EB",
    )
    systolic = (
        alt.Chart(_segmented(plot_df, "systolic_bp"))
        .mark_line(point={"size": 28, "filled": True}, strokeWidth=1.75)
        .encode(
            x=alt.X("plot_time:T", title=None, axis=axis),
            y=alt.Y(
                "systolic_bp:Q",
                title="mmHg",
                scale=alt.Scale(zero=False),
                axis=y_axis,
            ),
            color=alt.value("#E45B5B"),
            detail="segment:N",
            tooltip=[
                alt.Tooltip("date:T", title="日期"),
                alt.Tooltip("slot:N", title="时段"),
                alt.Tooltip("systolic_bp:Q", title="高压"),
            ],
        )
    )
    diastolic = (
        alt.Chart(_segmented(plot_df, "diastolic_bp"))
        .mark_line(point={"size": 28, "filled": True}, strokeWidth=1.75)
        .encode(
            x=alt.X("plot_time:T", title=None, axis=axis),
            y=alt.Y(
                "diastolic_bp:Q",
                title="mmHg",
                scale=alt.Scale(zero=False),
                axis=y_axis,
            ),
            color=alt.value("#4F7FE0"),
            detail="segment:N",
            tooltip=[
                alt.Tooltip("date:T", title="日期"),
                alt.Tooltip("slot:N", title="时段"),
                alt.Tooltip("diastolic_bp:Q", title="低压"),
            ],
        )
    )
    systolic_ref = (
        alt.Chart(pd.DataFrame({"y": [140]}))
        .mark_rule(strokeDash=[4, 5], color="#D1D5DB", strokeWidth=1)
        .encode(y="y:Q")
    )
    diastolic_ref = (
        alt.Chart(pd.DataFrame({"y": [90]}))
        .mark_rule(strokeDash=[4, 5], color="#E5E7EB", strokeWidth=1)
        .encode(y="y:Q")
    )
    return (
        (systolic + diastolic + systolic_ref + diastolic_ref)
        .properties(height=210)
        .configure_view(strokeWidth=0)
        .configure_axis(labelFontSize=11, titleFontSize=11)
        .interactive()
    )


def to_assessment(payload: dict) -> Assessment:
    return Assessment(**payload)


def state_label(state: str | None) -> str:
    if not state:
        return "未判读"
    return STATE_LABELS.get(state, state)


def format_mean(assessment: Assessment) -> str:
    sys_mean = assessment.bp.get("sys_mean_7d")
    dia_mean = assessment.bp.get("dia_mean_7d")
    if sys_mean is None and dia_mean is None:
        return "—"
    sys_text = "—" if sys_mean is None else f"{sys_mean:.0f}"
    dia_text = "—" if dia_mean is None else f"{dia_mean:.0f}"
    return f"{sys_text} / {dia_text}"


def format_rate(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.0%}"


def format_completion(assessment: Assessment) -> str:
    """用户视图用定性完成度，避免堆百分比 KPI。"""
    rate = assessment.adherence.get("rate_7d")
    if rate is None:
        return "—"
    value = float(rate)
    if value < 0.4:
        return "偏低"
    if value < 0.75:
        return "较完整"
    return "完整"


def user_status_title(state: str | None) -> str:
    """患者页展示用语；内部 State Code 仍只在 Debug。"""
    mapping = {
        "MONITORING_GAP": "监测暂时断了",
        "ESCALATION_REQUIRED": "需要专业关注",
        "SUSTAINED_HIGH": "目前仍偏高",
        "INSUFFICIENT_DATA": "记录还不够",
        "MORNING_SURGE": "早晚差别比较大",
        "IMPROVING": "正在变好",
        "STABLE_MAINTAIN": "目前比较平稳",
    }
    if not state:
        return "未判读"
    return mapping.get(state, state_label(state))


def user_status_sub(state: str | None) -> str:
    mapping = {
        "MONITORING_GAP": "最近记录断了一些",
        "ESCALATION_REQUIRED": "过去30天有一次异常读数",
        "SUSTAINED_HIGH": "近两周出现下降，整体仍偏高",
        "INSUFFICIENT_DATA": "先把测量补起来再判断",
        "MORNING_SURGE": "可以把早晚记录留好",
        "IMPROVING": "先巩固现有节奏",
        "STABLE_MAINTAIN": "保持现在的测量习惯即可",
    }
    if not state:
        return ""
    return mapping.get(state, "")


def _mm(value) -> str | None:
    if value is None:
        return None
    return f"{float(value):.0f}"


def _pct_int(value) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def health_summary(assessment: Assessment) -> dict[str, object]:
    """理解层。行动层由 ActionPlan / Workspace 负责。"""
    return actions.health_summary_view(assessment)


def compose_coach_text(reply: dict) -> str:
    parts = [reply.get("fact"), reply.get("explain"), reply.get("action")]
    return "\n".join(str(part).strip() for part in parts if part and str(part).strip())


def escalation_text(reply: dict, assessment: Assessment) -> str:
    code = reply.get("escalation_action") or assessment.escalation_action
    if not assessment.escalation_required and not code:
        return ""
    return ESCALATION_NL.get(code, "")


def family_copy(patient_name: str, reply: dict) -> str:
    fact = str(reply.get("fact") or "").replace("你", patient_name)
    explain = str(reply.get("explain") or "").replace("你", patient_name)
    action = str(reply.get("action") or "")
    body = " ".join(part for part in (fact, explain) if part).strip()
    return (
        f"【家属视角 · 演示未发送】{patient_name}最近：{body} 建议：{action}"
    )


def reply_payload(result: dict) -> dict:
    return {
        key: result.get(key)
        for key in ("fact", "explain", "action", "escalation_action", "disclaimers")
    }


def init_session() -> None:
    defaults = {
        "assess_nonce": 0,
        "current_patient": None,
        "chat_log": [],
        "llm_history": [],
        "push_cards": {},
        "action_plans": {},
        "debug_prompt": None,
        "debug_reply": None,
        "debug_guard": None,
        "debug_scene": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_conversation() -> None:
    st.session_state.chat_log = []
    st.session_state.llm_history = []
    st.session_state.push_cards = {}
    st.session_state.debug_prompt = None
    st.session_state.debug_reply = None
    st.session_state.debug_guard = None
    st.session_state.debug_scene = None


def load_plan(patient_id: str, assessment: Assessment) -> actions.ActionPlan:
    stored = (st.session_state.action_plans or {}).get(patient_id)
    expected = actions.build_action_plan(assessment)
    if stored and stored.get("action_type") == expected.action_type:
        return actions.ActionPlan.from_dict(stored)
    st.session_state.action_plans[patient_id] = expected.to_dict()
    return expected


def save_plan(patient_id: str, plan: actions.ActionPlan) -> None:
    st.session_state.action_plans[patient_id] = plan.to_dict()


def apply_plan_event(
    patient_id: str,
    plan: actions.ActionPlan,
    event: str,
    value: str | None = None,
) -> actions.ActionPlan:
    updated = actions.apply_event(plan, event, value)
    save_plan(patient_id, updated)
    return updated


def call_coach(
    assessment: Assessment,
    playbook: dict,
    user_msg: str,
    history: list[dict[str, str]] | None = None,
    scene: str | None = None,
    display_name: str | None = None,
    action_plan: actions.ActionPlan | None = None,
) -> dict:
    recent = list(history or [])
    conv = classify_conversation_intent(user_msg, recent)
    if scene:
        fewshots = get_fewshots(assessment.state) if assessment.state else []
    elif conv != CONV_HEALTH:
        fewshots = get_conversation_fewshots(conv)
    else:
        fewshots = get_fewshots(assessment.state) if assessment.state else []
    messages = build_messages(
        assessment_json=assessment,
        playbook=playbook,
        fewshots=fewshots,
        user_msg=user_msg,
        history=recent,
        scene=scene,
        display_name=display_name,
        action_plan_brief=actions.plan_brief(action_plan) if action_plan and not scene else None,
    )
    st.session_state.debug_prompt = messages
    st.session_state.debug_scene = scene
    try:
        if scene:
            result = agent.generate_push(assessment, playbook, scene)
        else:
            result = agent.chat(
                assessment=assessment,
                playbook=playbook,
                user_msg=user_msg,
                history=recent,
                display_name=display_name,
                action_plan_brief=actions.plan_brief(action_plan) if action_plan else None,
            )
    except Exception:
        fallback = guard.fallback(
            assessment,
            playbook,
            scene=scene,
            user_query=user_msg,
            history=recent,
            display_name=display_name,
        )
        result = {
            **fallback,
            "degraded": True,
            "reasons": ["模型调用失败，已使用安全模板"],
        }
    st.session_state.debug_reply = result
    st.session_state.debug_guard = guard.inspect(result, assessment)
    return result


def render_reply_footer(
    assessment: Assessment,
    reply: dict,
    family_on: bool,
    patient_name: str,
    user_facing: bool = True,
) -> None:
    if not user_facing:
        bits = [f"状态：{state_label(assessment.state)} · {assessment.state or ''}"]
        if reply.get("degraded"):
            bits.append("已使用安全模板")
        st.caption(" · ".join(bits))
    advice = escalation_text(reply, assessment)
    if advice and not user_facing:
        st.caption(advice)
    if family_on:
        st.caption(family_copy(patient_name, reply))


def render_push_card(
    scene_id: str,
    card: dict,
    assessment: Assessment,
    family_on: bool,
    patient_name: str,
    user_facing: bool = True,
) -> None:
    scene = SCENES[scene_id]
    title = SCENE_USER_LABELS.get(scene_id, scene["label"])
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(compose_coach_text(card))
        render_reply_footer(
            assessment,
            card,
            family_on,
            patient_name,
            user_facing=user_facing,
        )


def inject_styles() -> None:
    st.markdown(
        """
        <style>
          :root {
            --bp-bg: #F3F4F6;
            --bp-surface: #FFFFFF;
            --bp-text: #1C1C1E;
            --bp-muted: #6B7280;
            --bp-accent: #4F7FE0;
            --bp-accent-soft: #EEF3FC;
            --bp-warn: #D97757;
            --bp-warn-soft: #FBF1EC;
            --bp-ok: #3D8B6E;
            --bp-ok-soft: #EDF7F2;
            --bp-line: #E5E7EB;
            --bp-radius: 16px;
          }
          html, body, [data-testid="stAppViewContainer"] {
            background: var(--bp-bg) !important;
            color: var(--bp-text);
            font-family: "SF Pro Text", "PingFang SC", "Noto Sans SC",
              "Microsoft YaHei", system-ui, sans-serif;
          }
          [data-testid="stHeader"] { background: rgba(243,244,246,0.92); }
          [data-testid="stToolbar"] { background: transparent; }
          .block-container {
            padding-top: 3.25rem;
            padding-bottom: 3.5rem;
            max-width: 1120px;
          }
          [data-testid="stSidebar"] {
            background: #F7F8FA !important;
            border-right: 1px solid var(--bp-line);
          }
          [data-testid="stSidebar"] * { color: var(--bp-text); }
          .disclaimer-banner {
            background: #FFF9F0;
            border: 1px solid #F0E2C8;
            color: #7A6548;
            border-radius: 12px;
            padding: 0.75rem 1rem;
            margin: 0.35rem 0 1.1rem 0;
            font-size: 0.9rem;
            line-height: 1.5;
            overflow: visible;
            display: block;
            box-sizing: border-box;
          }
          .bp-brand { margin: 0 0 1.25rem 0; }
          .bp-brand h1 {
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin: 0 0 0.25rem 0;
            color: var(--bp-text);
          }
          .bp-brand p {
            margin: 0;
            color: var(--bp-muted);
            font-size: 0.95rem;
          }
          .bp-card {
            background: var(--bp-surface);
            border: 1px solid var(--bp-line);
            border-radius: var(--bp-radius);
            padding: 1.15rem 1.25rem 1.2rem;
            margin: 0 0 0.95rem 0;
          }
          .bp-card-quiet {
            background: var(--bp-surface);
            border: 1px solid var(--bp-line);
            border-radius: var(--bp-radius);
            padding: 0.95rem 1.15rem 0.85rem;
            margin: 0 0 0.95rem 0;
          }
          .bp-section-label {
            font-size: 0.78rem;
            color: var(--bp-muted);
            margin: 0 0 0.35rem 0;
          }
          .bp-status-grid {
            display: grid;
            grid-template-columns: 1.35fr 1fr;
            gap: 1.5rem;
            align-items: center;
          }
          .bp-status-title {
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin: 0 0 0.2rem 0;
            line-height: 1.25;
          }
          .bp-status-sub {
            margin: 0;
            color: var(--bp-muted);
            font-size: 0.9rem;
          }
          .bp-metrics {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.25rem;
          }
          .bp-metric-label {
            font-size: 0.78rem;
            color: var(--bp-muted);
            margin-bottom: 0.2rem;
          }
          .bp-metric-value {
            font-size: 1.55rem;
            font-weight: 650;
            letter-spacing: -0.02em;
            line-height: 1.2;
          }
          .bp-trend-head {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: baseline;
            margin-bottom: 0.35rem;
          }
          .bp-trend-head strong {
            font-size: 0.98rem;
            font-weight: 600;
          }
          .bp-trend-legend {
            color: var(--bp-muted);
            font-size: 0.78rem;
          }
          .bp-dot-sys { color: #E45B5B; }
          .bp-dot-dia { color: #4F7FE0; }
          .bp-coach-eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            color: var(--bp-accent);
            font-size: 0.84rem;
            font-weight: 600;
            margin: 0 0 0.75rem 0;
          }
          .bp-coach-eyebrow span {
            width: 7px; height: 7px; border-radius: 99px;
            background: var(--bp-accent); display: inline-block;
          }
          .bp-insight {
            font-size: 1.2rem;
            font-weight: 700;
            line-height: 1.45;
            letter-spacing: -0.015em;
            margin: 0.15rem 0 0.85rem 0;
          }
          .bp-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.35rem;
          }
          .bp-chip {
            background: var(--bp-accent-soft);
            color: var(--bp-text);
            border-radius: 12px;
            padding: 0.55rem 0.8rem;
            font-size: 0.86rem;
            line-height: 1.35;
          }
          .bp-chip::before {
            content: "";
            display: inline-block;
            width: 6px; height: 6px; border-radius: 99px;
            background: var(--bp-accent);
            margin-right: 0.45rem;
            vertical-align: middle;
          }
          .bp-action-shell {
            border-radius: var(--bp-radius);
            border: 1.5px solid rgba(79,127,224,0.35);
            background: var(--bp-surface);
            padding: 0.35rem 0.2rem 0.55rem;
            margin: 0 0 1rem 0;
          }
          .bp-action-shell.handoff {
            border-color: rgba(217,119,87,0.42);
          }
          .bp-action-shell.maintain {
            border-color: rgba(79,127,224,0.22);
          }
          .bp-action-anchor { display: none; }
          /* Action Workspace：紧跟锚点后的边框容器，视觉权重最高 */
          div.stElementContainer:has(.bp-action-anchor.restore) + div [data-testid="stVerticalBlockBorderWrapper"],
          div[data-testid="stElementContainer"]:has(.bp-action-anchor.restore) + div [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1.5px solid rgba(79,127,224,0.38) !important;
            border-radius: 16px !important;
            background: #fff !important;
            padding: 0.35rem 0.55rem 0.75rem !important;
            box-shadow: 0 8px 28px rgba(31,41,55,0.04);
          }
          div.stElementContainer:has(.bp-action-anchor.handoff) + div [data-testid="stVerticalBlockBorderWrapper"],
          div[data-testid="stElementContainer"]:has(.bp-action-anchor.handoff) + div [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1.5px solid rgba(217,119,87,0.42) !important;
            border-radius: 16px !important;
            background: #fff !important;
            padding: 0.35rem 0.55rem 0.75rem !important;
            box-shadow: 0 8px 28px rgba(31,41,55,0.04);
          }
          div.stElementContainer:has(.bp-action-anchor.maintain) + div [data-testid="stVerticalBlockBorderWrapper"],
          div[data-testid="stElementContainer"]:has(.bp-action-anchor.maintain) + div [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1.5px solid rgba(79,127,224,0.22) !important;
            border-radius: 16px !important;
            background: #fff !important;
            padding: 0.35rem 0.55rem 0.75rem !important;
            box-shadow: 0 8px 28px rgba(31,41,55,0.04);
          }
          .bp-action-title {
            font-size: 1.15rem;
            font-weight: 700;
            margin: 0.35rem 0.35rem 0.15rem;
          }
          .bp-action-desc {
            color: var(--bp-muted);
            font-size: 0.9rem;
            margin: 0 0.35rem 0.55rem;
          }
          .bp-must {
            background: var(--bp-warn-soft);
            color: var(--bp-warn);
            border-radius: 12px;
            padding: 0.7rem 0.9rem;
            font-size: 0.9rem;
            font-weight: 600;
            margin: 0.4rem 0 0.75rem;
          }
          .bp-steps {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.65rem;
            margin: 0.35rem 0 0.75rem;
          }
          .bp-step {
            background: var(--bp-accent-soft);
            border-radius: 12px;
            padding: 0.8rem 0.85rem;
          }
          .bp-step.ok { background: var(--bp-ok-soft); }
          .bp-step-k {
            font-size: 0.75rem;
            color: var(--bp-muted);
            margin-bottom: 0.25rem;
          }
          .bp-step-v {
            font-size: 0.92rem;
            font-weight: 600;
            line-height: 1.35;
          }
          .bp-pill {
            display: inline-block;
            background: var(--bp-ok-soft);
            color: var(--bp-ok);
            border-radius: 999px;
            padding: 0.35rem 0.8rem;
            font-size: 0.82rem;
            font-weight: 600;
            margin: 0.15rem 0 0.55rem;
          }
          .bp-chat-wrap {
            background: var(--bp-surface);
            border: 1px solid var(--bp-line);
            border-radius: var(--bp-radius);
            padding: 0.85rem 1rem 0.35rem;
            margin: 0.35rem 0 0.5rem;
            opacity: 0.98;
          }
          .bp-chat-wrap h3 {
            font-size: 0.95rem;
            font-weight: 600;
            margin: 0 0 0.55rem 0;
          }
          .bp-suggest {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin: 0 0 0.65rem 0;
          }
          .bp-suggest span {
            background: var(--bp-accent-soft);
            color: var(--bp-accent);
            border-radius: 999px;
            padding: 0.3rem 0.7rem;
            font-size: 0.78rem;
          }
          div[data-testid="stChatInput"] {
            margin-top: 0.15rem;
          }
          .stButton > button[kind="primary"],
          .stButton > button[data-testid="baseButton-primary"] {
            background: var(--bp-accent) !important;
            border-color: var(--bp-accent) !important;
            color: #fff !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
          }
          .stButton > button {
            border-radius: 12px !important;
            border-color: var(--bp-line) !important;
          }
          div[data-baseweb="radio"] label {
            background: var(--bp-surface);
            border: 1px solid var(--bp-line);
            border-radius: 12px;
            padding: 0.55rem 0.75rem;
            margin-bottom: 0.35rem;
          }
          [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px !important;
          }
          @media (max-width: 900px) {
            .bp-status-grid { grid-template-columns: 1fr; }
            .bp-steps { grid-template-columns: 1fr; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_status_hero(assessment: Assessment) -> None:
    title = html.escape(user_status_title(assessment.state))
    sub = html.escape(user_status_sub(assessment.state))
    mean = html.escape(format_mean(assessment))
    done = html.escape(format_completion(assessment))
    st.markdown(
        f"""
        <div class="bp-card">
          <div class="bp-status-grid">
            <div>
              <div class="bp-section-label">当前情况</div>
              <div class="bp-status-title">{title}</div>
              <p class="bp-status-sub">{sub}</p>
            </div>
            <div class="bp-metrics">
              <div>
                <div class="bp-metric-label">这周平均血压</div>
                <div class="bp-metric-value">{mean}</div>
              </div>
              <div>
                <div class="bp-metric-label">测量完成情况</div>
                <div class="bp-metric-value">{done}</div>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(assessment: Assessment) -> None:
    render_status_hero(assessment)


def render_user_view(
    patient: dict,
    plot_df: pd.DataFrame,
    assessment: Assessment,
    playbook: dict,
    family_on: bool,
) -> None:
    patient_id = patient["patient_id"]
    plan = load_plan(patient_id, assessment)
    render_status_hero(assessment)

    st.markdown(
        """
        <div class="bp-card-quiet" style="padding-bottom:0.25rem;margin-bottom:0.35rem;">
          <div class="bp-trend-head">
            <strong>30 天血压趋势</strong>
            <div class="bp-trend-legend">
              <span class="bp-dot-sys">●</span> 高压　
              <span class="bp-dot-dia">●</span> 低压　
              参考线 140 / 90 · 漏测处断线
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.altair_chart(build_bp_chart(plot_df), width="stretch")

    render_summary(assessment)
    plan = render_workspace(patient_id, assessment, plan)

    st.markdown(
        """
        <div class="bp-chat-wrap">
          <h3>继续问教练</h3>
          <div class="bp-suggest">
            <span>我最近怎么样？</span>
            <span>那早上呢？</span>
            <span>我该怎么做？</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for item in st.session_state.chat_log:
        with st.chat_message(item["role"]):
            st.write(item["content"])
            if item["role"] == "assistant":
                render_reply_footer(
                    assessment,
                    item.get("reply") or {},
                    family_on,
                    patient["short_name"],
                    user_facing=True,
                )

    prompt = st.chat_input("有哪里拿不准，直接问我…")
    if prompt:
        st.session_state.chat_log.append({"role": "user", "content": prompt, "reply": None})
        event = actions.classify_execution_event(prompt, plan)
        if event:
            plan = apply_plan_event(patient_id, plan, event)
            if event == "visit_ready" and not plan.handoff_text:
                plan = apply_plan_event(
                    patient_id,
                    plan,
                    "generate_handoff",
                    actions.build_visit_summary(assessment),
                )
            result = {
                **actions.execution_reply(plan, event),
                "escalation_action": assessment.escalation_action,
                "disclaimers": [],
                "degraded": False,
            }
        else:
            with st.spinner("教练正在回复…"):
                result = call_coach(
                    assessment,
                    playbook,
                    prompt,
                    history=st.session_state.llm_history,
                    scene=None,
                    display_name=patient["short_name"],
                    action_plan=plan,
                )
        payload = reply_payload(result)
        st.session_state.llm_history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        st.session_state.chat_log.append(
            {
                "role": "assistant",
                "content": compose_coach_text(result),
                "reply": result,
            }
        )
        st.rerun()


def render_summary(assessment: Assessment) -> None:
    summary = health_summary(assessment)
    insight = html.escape(str(summary.get("insight") or ""))
    evidence = summary.get("evidence") or []
    chips = "".join(
        f'<div class="bp-chip">{html.escape(str(item))}</div>' for item in evidence[:2]
    )
    st.markdown(
        f"""
        <div class="bp-card">
          <div class="bp-coach-eyebrow"><span></span>AI 教练 · 本周健康总结</div>
          <div class="bp-section-label">这周最值得关注</div>
          <div class="bp-insight">{insight}</div>
          <div class="bp-section-label">为什么</div>
          <div class="bp-chips">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_workspace(
    patient_id: str,
    assessment: Assessment,
    plan: actions.ActionPlan,
) -> actions.ActionPlan:
    if plan.action_type == actions.CLINICAL_HANDOFF:
        shell = "handoff"
        desc = "先复测一次，并尽快让医生看看。"
    elif plan.action_type == actions.MAINTAIN_PROGRESS:
        shell = "maintain"
        desc = "接下来只验证一件事：这个变化能不能保持。"
    else:
        shell = "restore"
        desc = "给原本的测量找一个更容易记住的生活节点。"

    st.markdown(
        f"""
        <div class="bp-action-anchor {shell}"></div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="bp-action-title">{html.escape(plan.title)}</div>
            <div class="bp-action-desc">{html.escape(desc)}</div>
            """,
            unsafe_allow_html=True,
        )
        if plan.action_type == actions.RESTORE_ROUTINE:
            plan = _workspace_restore(patient_id, plan)
        elif plan.action_type == actions.CLINICAL_HANDOFF:
            plan = _workspace_handoff(patient_id, assessment, plan)
        else:
            plan = _workspace_maintain(assessment, plan)
    return plan


def _workspace_restore(patient_id: str, plan: actions.ActionPlan) -> actions.ActionPlan:
    st.caption("不是改测量频率，只是把下一次测量绑到一个容易记住的节点。")
    options = list(actions.TRIGGER_OPTIONS)
    current = plan.trigger_node if plan.trigger_node in options else options[0]
    choice = st.radio(
        "固定生活节点",
        options,
        index=options.index(current),
        key=f"node_{patient_id}",
        label_visibility="collapsed",
    )
    if choice != plan.trigger_node:
        plan = apply_plan_event(patient_id, plan, "set_trigger", choice)
        st.rerun()
    if choice == "自己定一个":
        custom = st.text_input(
            "写一个你每天都会碰到的节点",
            value=plan.custom_trigger or "",
            key=f"custom_{patient_id}",
        )
        if custom.strip() and custom.strip() != (plan.custom_trigger or ""):
            plan = apply_plan_event(patient_id, plan, "set_custom_trigger", custom.strip())
            st.rerun()
    st.write(plan.execution_support)
    if plan.status == "done":
        st.success("今天这次已经接上了。")
        st.caption("下次我会先看看这个节奏有没有接起来。")
        return plan
    left, right = st.columns(2)
    with left:
        if st.button(
            "今天已测",
            key=f"measured_{patient_id}",
            type="primary",
            width="stretch",
        ):
            apply_plan_event(patient_id, plan, "measure_done")
            st.rerun()
    with right:
        if st.button("还没测", key=f"skip_{patient_id}", width="stretch"):
            apply_plan_event(patient_id, plan, "measure_skip")
            st.rerun()
    if plan.status == "skipped":
        st.write("是容易忘，还是这个时间不方便？")
        a, b = st.columns(2)
        with a:
            if st.button("容易忘", key=f"forget_{patient_id}", width="stretch"):
                apply_plan_event(patient_id, plan, "friction_forget")
                st.rerun()
        with b:
            if st.button("时间不方便", key=f"inconv_{patient_id}", width="stretch"):
                apply_plan_event(patient_id, plan, "friction_inconvenient")
                st.rerun()
    st.caption("下次我会先看看这个节奏有没有接起来。")
    return plan


def _workspace_handoff(
    patient_id: str,
    assessment: Assessment,
    plan: actions.ActionPlan,
) -> actions.ActionPlan:
    st.markdown(
        '<div class="bp-must">必须先做：按规范复测一次确认，并尽快就医。</div>',
        unsafe_allow_html=True,
    )
    if st.button(
        "生成就诊摘要",
        key=f"handoff_{patient_id}",
        type="primary",
        width="stretch",
    ):
        text = actions.build_visit_summary(assessment)
        plan = apply_plan_event(patient_id, plan, "generate_handoff", text)
        st.rerun()
    if plan.handoff_text:
        with st.container(border=True):
            st.markdown("**需要重点告诉医生 / 可以问医生**")
            st.code(plan.handoff_text, language="markdown")
            st.caption("可点右上角复制。这是就诊准备材料，不是诊断，也不是用药建议。")
    else:
        st.caption("点上方按钮后，会根据当前记录整理一份给医生看的摘要。")
    a, b = st.columns(2)
    with a:
        if st.button("已复测", key=f"retest_{patient_id}", width="stretch"):
            apply_plan_event(patient_id, plan, "remeasured")
            st.rerun()
    with b:
        if st.button("准备就医", key=f"visit_{patient_id}", width="stretch"):
            apply_plan_event(patient_id, plan, "ready_to_visit")
            st.rerun()
    bits = []
    if plan.remeasured:
        bits.append("已复测")
    if plan.ready_to_visit:
        bits.append("准备就医")
    if bits:
        st.success(" · ".join(bits))
    return plan


def _workspace_maintain(assessment: Assessment, plan: actions.ActionPlan) -> actions.ActionPlan:
    summary = health_summary(assessment)
    evidence = list(summary.get("evidence") or [])
    now_text = evidence[0] if evidence else "最近两周出现下降"
    next_text = "保持当前测量节奏"
    review_text = "新增一周记录后再次比较"
    st.markdown(
        f"""
        <div class="bp-steps">
          <div class="bp-step">
            <div class="bp-step-k">现在</div>
            <div class="bp-step-v">{html.escape(str(now_text))}</div>
          </div>
          <div class="bp-step">
            <div class="bp-step-k">下一步</div>
            <div class="bp-step-v">{html.escape(next_text)}</div>
          </div>
          <div class="bp-step ok">
            <div class="bp-step-k">复盘</div>
            <div class="bp-step-v">{html.escape(review_text)}</div>
          </div>
        </div>
        <div class="bp-pill">等待下一周期数据</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("本轮观察变化，下一轮验证变化是否继续。暂时不增加新的管理任务。")
    return plan


def render_debug_view(
    assessment: Assessment,
    playbook: dict,
    patient_id: str,
) -> None:
    with st.expander("重新运行判读", expanded=False):
        st.caption(
            "会清空缓存并重新执行同一套 Rules / State。"
            "数据不变时，结果也不会变。仅供开发/演示核对。"
        )
        if st.button("重新运行判读", width="stretch"):
            st.session_state.assess_nonce += 1
            cached_assessment.clear()
            st.rerun()

    with st.expander("场景卡片（内部）", expanded=False):
        st.caption("患者视图不再展示 Scene。这里用于验证 State × Scene / Prompt / Guard。")
        b1, b2, b3 = st.columns(3)
        clicked = None
        with b1:
            if st.button("S1 依从提醒", key="debug_s1", width="stretch"):
                clicked = "S1"
        with b2:
            if st.button("S2 异常响应", key="debug_s2", width="stretch"):
                clicked = "S2"
        with b3:
            if st.button("S3 周度总结", key="debug_s3", width="stretch"):
                clicked = "S3"
        if clicked:
            card = call_coach(
                assessment,
                playbook,
                push_user_msg(clicked),
                history=[],
                scene=clicked,
            )
            st.session_state.push_cards[clicked] = card
        cards = st.session_state.push_cards
        if not cards:
            st.caption("尚未生成场景卡片。")
        else:
            for scene_id in ("S1", "S2", "S3"):
                card = cards.get(scene_id)
                if not card:
                    continue
                st.markdown(
                    f"**{scene_id} {SCENES[scene_id]['label']}** · "
                    f"degraded={bool(card.get('degraded'))}"
                )
                st.json(reply_payload(card))

    with st.expander("ActionPlan（内部）", expanded=False):
        plan = (st.session_state.action_plans or {}).get(patient_id)
        if not plan:
            st.caption("尚未生成 ActionPlan。")
        else:
            st.json(plan)

    with st.expander("模型运行状态", expanded=False):
        runtime = agent.describe_runtime()
        st.caption("事实源：agent.describe_runtime() · 不含 API Key")
        st.json(
            {
                "api_key_configured": runtime.get("api_key_configured"),
                "config_source": runtime.get("config_source"),
                "model_call_succeeded": runtime.get("model_call_succeeded"),
                "fallback_used": runtime.get("fallback_used"),
                "degraded": runtime.get("degraded"),
                "response_model": runtime.get("response_model"),
                "requested_model": runtime.get("requested_model"),
                "attempts": runtime.get("attempts"),
                "attempt_details": runtime.get("attempt_details"),
            }
        )

    with st.expander("判读依据", expanded=False):
        st.caption(
            f"risk_level = {assessment.risk_level}（描述性指标，不驱动行为）"
        )
        st.json(json.loads(assessment.to_json()))

    with st.expander("state / strategy", expanded=False):
        st.markdown(f"**当前状态：** `{assessment.state}` · {state_label(assessment.state)}")
        st.markdown(f"**goal：** {playbook.get('goal', '')}")
        st.markdown("**must_do**")
        for item in playbook.get("must_do") or []:
            st.markdown(f"- {item}")
        st.markdown("**must_not**")
        for item in playbook.get("must_not") or []:
            st.markdown(f"- {item}")

    with st.expander("Prompt", expanded=False):
        messages = st.session_state.debug_prompt
        if not messages:
            st.caption("尚未调用模型。生成推送或发送对话后，这里会显示首次请求的完整内容（不含自动重试轮）。")
        else:
            if st.session_state.debug_scene:
                st.caption(f"最近一次调用场景：{st.session_state.debug_scene}")
            for index, message in enumerate(messages, start=1):
                st.markdown(f"**[{index}] {message.get('role')}**")
                st.code(message.get("content") or "", language="markdown")

    with st.expander("Guard", expanded=False):
        rows = st.session_state.debug_guard
        if not rows:
            st.caption("尚未调用模型，暂无 G1–G6 结果。")
        else:
            for row in rows:
                mark = "通过" if row.get("ok") else "拦截"
                st.markdown(f"**{row.get('id')} {row.get('name')}** · {mark}")
                if row.get("id") == "G4b":
                    expected = row.get("expected")
                    actual = row.get("actual")
                    triggered = "是" if row.get("escalation_required") else "否"
                    st.caption(
                        f"escalation_required={triggered}　"
                        f"校验：判读结果={expected!s}　回复={actual!s}"
                    )
                for reason in row.get("reasons") or []:
                    st.caption(str(reason))
            if st.session_state.debug_reply and st.session_state.debug_reply.get("reasons"):
                st.markdown("**最近一次未通过原因（含重试后降级）**")
                for reason in st.session_state.debug_reply.get("reasons") or []:
                    st.caption(str(reason))

    with st.expander("FHIR Bundle 片段", expanded=False):
        st.code(load_fhir_preview(patient_id, 2000), language="json")

    with st.expander("最近一次评测报告摘要", expanded=False):
        st.code(load_eval_summary(), language="markdown")


st.set_page_config(page_title="血压管家 · 研究原型", page_icon="🩺", layout="wide")
init_session()
inject_styles()

st.markdown(
    '<div class="disclaimer-banner">研究原型，非医疗器械，不构成医疗建议</div>',
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div class="bp-brand">
      <h1>血压管家</h1>
      <p>陪你看懂记录，也帮你把下一步做起来</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.caption("患者")
    selected_name = st.selectbox("选择患者", list(PATIENTS.keys()), label_visibility="collapsed")
    patient = PATIENTS[selected_name]
    if st.session_state.current_patient != selected_name:
        st.session_state.current_patient = selected_name
        reset_conversation()

    assessment = to_assessment(
        cached_assessment(patient["patient_id"], st.session_state.assess_nonce)
    )
    playbook = get_playbook(assessment.state) if assessment.state else {}

    st.caption("当前情况")
    st.markdown(f"#### {user_status_title(assessment.state)}")
    sub = user_status_sub(assessment.state)
    if sub:
        st.caption(sub)

    family_on = st.toggle(
        "家属共享",
        value=False,
        help="仅影响是否显示家属视角文案，不会发送真实消息。",
    )
    if family_on:
        st.caption("已开启家属视角文案（演示，未发送）")

    if not api_configured():
        st.warning("模型配置缺失。对话与推送将使用备用回复。")

plot_df = load_patient_data(patient["file"])

user_tab, debug_tab = st.tabs(["用户视图", "Debug / 产品验证"])
with user_tab:
    render_user_view(patient, plot_df, assessment, playbook, family_on)
with debug_tab:
    st.caption("产品验证面板，默认不展开各区块。")
    render_debug_view(assessment, playbook, patient["patient_id"])
