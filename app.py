from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).parent / "data" / "patients"

PATIENTS = {
    "张阿姨（58岁）": {
        "file": "patient_001.csv",
        "age": 58,
        "status": "未控制期",
        "insight": (
            "近21天保持较规律测量，但第22天后测量频率明显下降。"
            "当前后期数据不足，建议优先关注监测依从性，"
            "而不是仅根据少量读数判断血压变化。"
        ),
    },
    "李叔叔（63岁）": {
        "file": "patient_002.csv",
        "age": 63,
        "status": "波动期",
        "insight": (
            "近30天收缩压波动较明显，早晨读数系统性高于晚上，"
            "且整体测量依从率约85%，建议继续关注不同时间段的血压变化。"
        ),
    },
    "王先生（45岁）": {
        "file": "patient_003.csv",
        "age": 45,
        "status": "改善期",
        "insight": (
            "前14天收缩压持续偏高，第15天后逐步下降，"
            "近期已接近138 mmHg，同时活动量增加，整体呈改善趋势。"
        ),
    },
}


@st.cache_data
def load_patient_data(filename: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / filename)
    df["date"] = pd.to_datetime(df["date"])
    df["systolic_bp"] = pd.to_numeric(df["systolic_bp"], errors="coerce")
    df["diastolic_bp"] = pd.to_numeric(df["diastolic_bp"], errors="coerce")
    hour_map = {"morning": 8, "evening": 20}
    df["plot_time"] = df["date"] + pd.to_timedelta(
        df["measurement_time"].map(hour_map),
        unit="h",
    )
    return df


def calc_compliance(df: pd.DataFrame) -> float:
    scheduled = df["scheduled"].sum()
    completed = df["completed"].sum()
    return completed / scheduled if scheduled else 0.0


def build_bp_chart(measured_df: pd.DataFrame) -> alt.Chart:
    base = alt.Chart(measured_df).encode(
        x=alt.X("plot_time:T", title="日期", axis=alt.Axis(format="%m-%d")),
    )

    systolic_line = base.mark_line(point=True, strokeWidth=2).encode(
        y=alt.Y("systolic_bp:Q", title="血压 (mmHg)", scale=alt.Scale(zero=False)),
        color=alt.value("#e45756"),
        tooltip=["date:T", "measurement_time:N", "systolic_bp:Q"],
    )

    diastolic_line = base.mark_line(point=True, strokeWidth=2).encode(
        y=alt.Y("diastolic_bp:Q", title="血压 (mmHg)", scale=alt.Scale(zero=False)),
        color=alt.value("#4c78a8"),
        tooltip=["date:T", "measurement_time:N", "diastolic_bp:Q"],
    )

    systolic_ref = (
        alt.Chart(pd.DataFrame({"y": [140]}))
        .mark_rule(strokeDash=[6, 4], color="#888888")
        .encode(y="y:Q")
    )
    diastolic_ref = (
        alt.Chart(pd.DataFrame({"y": [90]}))
        .mark_rule(strokeDash=[6, 4], color="#aaaaaa")
        .encode(y="y:Q")
    )

    return (
        (systolic_line + diastolic_line + systolic_ref + diastolic_ref)
        .properties(height=420)
        .interactive()
    )


st.set_page_config(page_title="AI血压管理Agent Demo", page_icon="🩺", layout="wide")

st.title("AI血压管理Agent Demo")
st.caption("本 Demo 中的 140/90 参考线仅用于可视化对比，不代表个体化治疗目标。")

selected_name = st.selectbox("选择患者", list(PATIENTS.keys()))
patient = PATIENTS[selected_name]
df = load_patient_data(patient["file"])

measured = df[df["completed"] == 1].copy()
compliance = calc_compliance(df)
avg_systolic = measured["systolic_bp"].mean()
avg_diastolic = measured["diastolic_bp"].mean()

st.subheader("患者概况")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("年龄", f"{patient['age']} 岁")
col2.metric("患者状态", patient["status"])
col3.metric("30天测量依从率", f"{compliance:.1%}")
col4.metric("平均收缩压", f"{avg_systolic:.0f} mmHg")
col5.metric("平均舒张压", f"{avg_diastolic:.0f} mmHg")

st.subheader("血压趋势图")
st.caption("红色：收缩压 | 蓝色：舒张压 | 灰色虚线：Demo 参考线（140 / 90）")
st.altair_chart(build_bp_chart(measured), use_container_width=True)

st.subheader("AI健康洞察")
st.info(patient["insight"])
st.caption("以上洞察仅基于模拟数据趋势，不做疾病诊断，不改变药物方案，不代替医生。")
