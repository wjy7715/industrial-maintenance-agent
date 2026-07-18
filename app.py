from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from industrial_maintenance_agent import DiagnosisRequest, MaintenanceOrchestrator  # noqa: E402
from industrial_maintenance_agent.evaluation import run_retrieval_evaluation  # noqa: E402
from industrial_maintenance_agent.repositories import EquipmentRepository  # noqa: E402


st.set_page_config(page_title="工业运维 Agent", page_icon="🛠️", layout="wide")
st.title("🛠️ 多工具调用工业运维 Agent")
st.caption("设备故障查询 + 维修方案自动生成｜公开数据教学原型")

repository = EquipmentRepository(ROOT / "data" / "sample" / "equipment.json")
orchestrator = MaintenanceOrchestrator.from_project(ROOT)
equipment = repository.list_equipment()
ERROR_LABELS = {
    "VIBRATION_HIGH": "振动过高",
    "DISCHARGE_PRESSURE_LOW": "出口压力偏低",
    "BEARING_TEMPERATURE_HIGH": "轴承温度过高",
}

with st.sidebar:
    st.subheader("项目状态")
    st.success("离线诊断核心可用")
    st.info("Hermes 为可选展示适配器，不影响离线功能")
    report = run_retrieval_evaluation(ROOT)
    st.metric("检索评测 Top-1", f"{report.top1_accuracy:.1%}")
    st.metric("固定评测案例", report.total)
    st.warning("不连接、不控制任何真实设备")

left, right = st.columns([1, 1])
with left:
    st.subheader("故障描述")
    selected = st.selectbox(
        "设备",
        [item["equipment_id"] for item in equipment],
        format_func=lambda value: f"{value}｜离心泵",
    )
    symptom = st.text_area(
        "现象",
        value="泵振动明显，出口压力下降",
        height=120,
        help="系统只会检索有来源的维修知识，无匹配时不会猜测。",
    )
    submitted = st.button("开始诊断", type="primary", width="stretch")

with right:
    current = next(item for item in equipment if item["equipment_id"] == selected)
    st.subheader("最新遥测（仿真）")
    metrics = st.columns(2)
    values = current["latest_telemetry"]
    metrics[0].metric("出口压力", f"{values['pressure_bar']} bar")
    metrics[1].metric("振动", f"{values['vibration_mm_s']} mm/s")
    metrics[0].metric("温度", f"{values['temperature_c']} °C")
    metrics[1].metric("转速", f"{values['rotation_rpm']} rpm")
    if current["active_errors"]:
        translated_errors = [
            f"{ERROR_LABELS.get(code, '未翻译告警')}（{code}）"
            for code in current["active_errors"]
        ]
        st.warning("仿真设备活动告警：" + "、".join(translated_errors))
        st.caption("这是项目示例设备的故障数据，不是网页、电脑或真实设备报错。")
    else:
        st.success("仿真设备当前没有活动告警")

if submitted:
    try:
        plan = orchestrator.diagnose(DiagnosisRequest(selected, (symptom,)))
    except (ValueError, LookupError) as exc:
        st.error(str(exc))
    else:
        st.divider()
        status_col, risk_col, confirm_col = st.columns(3)
        status_col.metric("结果状态", "草稿")
        risk_col.metric("风险等级", plan.risk_level.upper())
        confirm_col.metric("人工确认", "必须")

        if not plan.corrective_actions:
            st.warning("当前知识库没有可靠匹配，未生成维修措施。")
        else:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("候选原因")
                for item in plan.candidate_causes:
                    st.markdown(f"- {item}")
                st.subheader("检查步骤")
                for index, item in enumerate(plan.inspection_steps, 1):
                    st.markdown(f"{index}. {item}")
            with c2:
                st.subheader("维修方案草稿")
                for index, item in enumerate(plan.corrective_actions, 1):
                    st.markdown(f"{index}. {item}")
                st.subheader("安全警告")
                for item in plan.safety_warnings:
                    st.warning(item)

        with st.expander("查看 Agent 工具执行轨迹", expanded=True):
            st.dataframe([item.__dict__ for item in plan.tool_trace], width="stretch")
        with st.expander("查看证据与来源"):
            for item in plan.evidence:
                st.markdown(f"**{item.kind}｜{item.source_name}**")
                st.write(item.summary)
                if item.source_url:
                    st.markdown(f"[打开来源]({item.source_url}) · {item.source_location}")
        st.caption("；".join(plan.limitations))
