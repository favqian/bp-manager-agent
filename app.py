from pathlib import Path

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


@st.cache_resource
def api_configured() -> bool:
    return agent.check_config()


def _segmented(plot_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """漏测记为空值后分段，折线在缺口处断开，不插值。"""
    work = plot_df[["plot_time", value_col, "date", "slot"]].copy()
    work["gap"] = work[value_col].isna()
    work["segment"] = work["gap"].cumsum()
    return work.loc[~work["gap"]]


def build_bp_chart(plot_df: pd.DataFrame) -> alt.Chart:
    systolic = (
        alt.Chart(_segmented(plot_df, "systolic_bp"))
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("plot_time:T", title="日期", axis=alt.Axis(format="%m-%d")),
            y=alt.Y("systolic_bp:Q", title="血压 (mmHg)", scale=alt.Scale(zero=False)),
            color=alt.value("#c45c4a"),
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
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("plot_time:T", title="日期", axis=alt.Axis(format="%m-%d")),
            y=alt.Y("diastolic_bp:Q", title="血压 (mmHg)", scale=alt.Scale(zero=False)),
            color=alt.value("#3d6f9a"),
            detail="segment:N",
            tooltip=[
                alt.Tooltip("date:T", title="日期"),
                alt.Tooltip("slot:N", title="时段"),
                alt.Tooltip("diastolic_bp:Q", title="低压"),
            ],
        )
    )
    systolic_ref = (
        alt.Chart(pd.DataFrame({"y": [140], "label": ["140"]}))
        .mark_rule(strokeDash=[6, 4], color="#8a8178")
        .encode(y="y:Q")
    )
    diastolic_ref = (
        alt.Chart(pd.DataFrame({"y": [90], "label": ["90"]}))
        .mark_rule(strokeDash=[6, 4], color="#b7aea6")
        .encode(y="y:Q")
    )
    return (
        (systolic + diastolic + systolic_ref + diastolic_ref)
        .properties(height=380)
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
          [data-testid="stHeader"] { background: rgba(255,255,255,0.92); }
          .block-container { padding-top: 3.4rem; padding-bottom: 4.5rem; max-width: 1180px; }
          .disclaimer-banner {
            background: #fff6e8;
            border: 1px solid #ead9b8;
            color: #5c4a32;
            border-radius: 10px;
            padding: 0.7rem 1rem;
            margin: 0 0 1rem 0;
            font-size: 0.92rem;
          }
          .kpi-row {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin: 4px 0 18px;
          }
          .kpi {
            background: #fffdfb;
            border: 1px solid #ece4d8;
            border-radius: 12px;
            padding: 14px 16px;
            min-height: 92px;
          }
          .kpi-label { font-size: 13px; color: #7a7168; }
          .kpi-value {
            font-size: 22px;
            font-weight: 650;
            margin-top: 8px;
            line-height: 1.35;
            word-break: break-word;
          }
          .scene-hint { color: #8a8178; font-size: 0.86rem; margin-bottom: 0.4rem; }
          @media (max-width: 900px) {
            .kpi-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(assessment: Assessment) -> None:
    items = [
        ("当前情况", state_label(assessment.state)),
        ("这周平均血压", format_mean(assessment)),
        ("本周测量完成度", format_rate(assessment.adherence.get("rate_7d"))),
    ]
    cards = "".join(
        f'<div class="kpi"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="kpi-row">{cards}</div>', unsafe_allow_html=True)


def render_user_view(
    patient: dict,
    plot_df: pd.DataFrame,
    assessment: Assessment,
    playbook: dict,
    family_on: bool,
) -> None:
    patient_id = patient["patient_id"]
    plan = load_plan(patient_id, assessment)
    render_kpis(assessment)

    st.subheader("30 天血压趋势")
    st.caption("红色：高压　蓝色：低压　灰色虚线：Demo 参考线 140 / 90　漏测处断线、不插值、不平滑")
    st.altair_chart(build_bp_chart(plot_df), width="stretch")

    st.subheader("AI 教练")
    render_summary(assessment)
    plan = render_workspace(patient_id, assessment, plan)

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

    prompt = st.chat_input("和健康教练说一句…")
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
    st.markdown("**本周健康总结**")
    st.caption("AI 帮我理解")
    st.markdown("**这周最值得关注**")
    st.write(str(summary.get("insight") or ""))
    st.markdown("**为什么这么判断**")
    for item in summary.get("evidence") or []:
        st.markdown(f"- {item}")


def render_workspace(
    patient_id: str,
    assessment: Assessment,
    plan: actions.ActionPlan,
) -> actions.ActionPlan:
    st.markdown(f"**{plan.title}**")
    st.caption("AI 接下来帮你做")
    with st.container(border=True):
        if plan.action_type == actions.RESTORE_ROUTINE:
            plan = _workspace_restore(patient_id, plan)
        elif plan.action_type == actions.CLINICAL_HANDOFF:
            plan = _workspace_handoff(patient_id, assessment, plan)
        else:
            plan = _workspace_maintain(assessment, plan)
    return plan


def _workspace_restore(patient_id: str, plan: actions.ActionPlan) -> actions.ActionPlan:
    st.markdown("**本周目标**")
    st.write("先把测量节奏重新接起来。")
    st.markdown("**执行支持**")
    st.caption("不是改测量频率，只是把下一次测量绑到一个容易记住的节点。")
    options = list(actions.TRIGGER_OPTIONS)
    current = plan.trigger_node if plan.trigger_node in options else options[0]
    choice = st.radio("固定生活节点", options, index=options.index(current), key=f"node_{patient_id}")
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
    st.markdown("**执行反馈**")
    if plan.status == "done":
        st.success("今天这次已经接上了。")
        st.caption(f"状态：{plan.status}")
        return plan
    left, right = st.columns(2)
    with left:
        if st.button("今天已测", key=f"measured_{patient_id}", width="stretch"):
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
    st.caption(f"状态：{plan.status}")
    return plan


def _workspace_handoff(
    patient_id: str,
    assessment: Assessment,
    plan: actions.ActionPlan,
) -> actions.ActionPlan:
    st.markdown("**本周目标**")
    st.write("把这次异常顺利带到医生那里。")
    st.markdown("**必须先做**")
    st.write("先按规范复测一次确认，并尽快就医。")
    st.markdown("**AI 产出：就诊摘要**")
    if st.button("生成就诊摘要", key=f"handoff_{patient_id}"):
        text = actions.build_visit_summary(assessment)
        plan = apply_plan_event(patient_id, plan, "generate_handoff", text)
        st.rerun()
    if plan.handoff_text:
        st.code(plan.handoff_text, language="markdown")
        st.caption("可点右上角复制。")
    else:
        st.caption("点上方按钮后，会根据当前记录整理一份给医生看的摘要。")
    st.markdown("**执行反馈**")
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
    st.caption(f"状态：{plan.status}")
    return plan


def _workspace_maintain(assessment: Assessment, plan: actions.ActionPlan) -> actions.ActionPlan:
    summary = health_summary(assessment)
    st.markdown("**现在看到的变化**")
    for item in summary.get("evidence") or []:
        st.markdown(f"- {item}")
    st.markdown("**这阶段要验证什么**")
    st.write("这个下降能不能继续保持。")
    st.markdown("**怎么做**")
    st.write("先保持现在的测量节奏。")
    st.write("暂时不增加新的管理任务。")
    st.markdown("**什么时候再看**")
    st.write("新增一周记录后，我继续用同样口径比较。")
    st.info("等待下一周期数据")
    st.caption(f"状态：{plan.status} · 本轮观察变化，下一轮验证变化")
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
st.title("血压管家")
st.caption("家庭血压监测的管理状态演示。140/90 仅用于可视化对比，不代表个体化治疗目标。")

with st.sidebar:
    st.markdown("**患者**")
    selected_name = st.selectbox("选择患者", list(PATIENTS.keys()), label_visibility="collapsed")
    patient = PATIENTS[selected_name]
    if st.session_state.current_patient != selected_name:
        st.session_state.current_patient = selected_name
        reset_conversation()

    assessment = to_assessment(
        cached_assessment(patient["patient_id"], st.session_state.assess_nonce)
    )
    playbook = get_playbook(assessment.state) if assessment.state else {}

    st.markdown("**当前情况**")
    st.markdown(f"### {state_label(assessment.state)}")

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
