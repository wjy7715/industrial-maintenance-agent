from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from industrial_maintenance_agent import DiagnosisRequest, MaintenanceOrchestrator  # noqa: E402
from industrial_maintenance_agent.domain import AccessContext  # noqa: E402
from industrial_maintenance_agent.governance.reviews import ExpertReviewService  # noqa: E402
from industrial_maintenance_agent.evaluation import (  # noqa: E402
    build_shadow_report,
    run_retrieval_evaluation,
)
from industrial_maintenance_agent.repositories import (  # noqa: E402
    EquipmentRepository,
    MaintenanceHistoryCsvRepository,
    TelemetryCsvRepository,
)
from industrial_maintenance_agent.safety import ToolPermissionRegistry  # noqa: E402


st.set_page_config(page_title="工业运维 Agent", page_icon="🛠️", layout="wide")
st.title("🛠️ 多工具调用工业运维 Agent")
st.caption("设备故障查询 + 维修方案自动生成｜公开数据教学原型")

history_repository = None
data_source_mode = st.sidebar.radio("遥测数据源", ["项目仿真数据", "上传只读 CSV"])
if data_source_mode == "上传只读 CSV":
    uploaded_telemetry = st.sidebar.file_uploader(
        "选择脱敏遥测快照",
        type=["csv"],
        help="只在当前会话内解析，不写回设备；请勿上传人员、客户或商业敏感信息。",
    )
    st.sidebar.download_button(
        "下载遥测 CSV 模板",
        data=(ROOT / "data" / "sample" / "telemetry_snapshot.csv").read_bytes(),
        file_name="telemetry_snapshot.csv",
        mime="text/csv",
    )
    uploaded_history = st.sidebar.file_uploader(
        "故障与维修闭环（可选）",
        type=["csv"],
        help="独立的只读历史事件源；不提供时沿用遥测快照中的活动告警。",
    )
    st.sidebar.download_button(
        "下载历史 CSV 模板",
        data=(ROOT / "data" / "sample" / "maintenance_history.csv").read_bytes(),
        file_name="maintenance_history.csv",
        mime="text/csv",
    )
    if uploaded_telemetry is None:
        st.info("请在左侧上传脱敏遥测 CSV；上传前不会运行诊断。")
        st.stop()
    try:
        repository = TelemetryCsvRepository.from_bytes(
            uploaded_telemetry.getvalue(), uploaded_telemetry.name
        )
    except ValueError as exc:
        st.error(f"CSV 校验失败：{exc}")
        st.stop()
    if uploaded_history is not None:
        try:
            history_repository = MaintenanceHistoryCsvRepository.from_bytes(
                uploaded_history.getvalue(), uploaded_history.name
            )
        except ValueError as exc:
            st.error(f"历史 CSV 校验失败：{exc}")
            st.stop()
else:
    repository = EquipmentRepository(ROOT / "data" / "sample" / "equipment.json")

role = st.sidebar.selectbox(
    "本地演示角色",
    ["technician", "domain_expert", "knowledge_admin", "administrator"],
)
st.sidebar.caption("仅用于演示授权逻辑，不等于企业账号登录或真实身份认证。")
access_context = AccessContext(
    actor_id=f"local-{role}",
    role=role,
    allowed_sites=("demo-site", "local-upload") if role != "administrator" else ("*",),
)

orchestrator = MaintenanceOrchestrator.from_project(
    ROOT,
    equipment=repository,
    history=history_repository,
)
sessions = orchestrator.sessions
equipment = repository.list_equipment()
source_metadata = repository.metadata
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
    with st.expander("工具权限策略"):
        st.caption("未注册工具默认拒绝；外部写入需确认；设备控制明确禁止。")
        st.dataframe(ToolPermissionRegistry().report(), width="stretch")
    if source_metadata.get("kind") == "user_imported_read_only":
        st.info(f"当前数据源：{source_metadata['name']}（只读、未独立核验）")
        if history_repository is not None:
            st.info(f"历史数据源：{history_repository.metadata['name']}（只读、未独立核验）")
        else:
            st.caption("历史数据源：沿用遥测快照中的活动告警；没有维修闭环记录")
    else:
        st.caption("当前数据源：项目仿真数据")
    if sessions is not None:
        recent_sessions = sessions.recent_sessions(limit=20)
        recent_count = len(recent_sessions)
        st.metric("本地审计会话", recent_count)
        with st.expander("最近诊断"):
            if not recent_sessions:
                st.caption("暂无已审计诊断")
            for item in recent_sessions[:5]:
                risk = item["plan"].get("risk_level", "unknown")
                st.caption(
                    f"{item['session_id'][:8]}｜{item['equipment_id']}｜{risk.upper()}｜{item['created_at']}"
                )

left, right = st.columns([1, 1])
with left:
    st.subheader("故障描述")
    selected = st.selectbox(
        "设备",
        [item["equipment_id"] for item in equipment],
        format_func=lambda value: value,
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
    source_title = (
        "用户导入遥测（只读）"
        if source_metadata.get("kind") == "user_imported_read_only"
        else "最新遥测（仿真）"
    )
    st.subheader(source_title)
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
        prefix = (
            "导入快照活动告警"
            if source_metadata.get("kind") == "user_imported_read_only"
            else "仿真设备活动告警"
        )
        st.warning(prefix + "：" + "、".join(translated_errors))
        if source_metadata.get("kind") == "user_imported_read_only":
            st.caption("告警来自上传快照，系统未连接设备，也未验证告警是否仍然有效。")
        else:
            st.caption("这是项目示例设备的故障数据，不是网页、电脑或真实设备报错。")
    else:
        st.success("当前快照没有活动告警")

if submitted:
    try:
        plan = orchestrator.diagnose(
            DiagnosisRequest(selected, (symptom,)), access=access_context
        )
    except (ValueError, LookupError, PermissionError) as exc:
        st.error(str(exc))
    else:
        st.session_state["last_plan"] = plan

plan = st.session_state.get("last_plan")
if plan is not None:
    st.divider()
    status_col, risk_col, confirm_col, session_col = st.columns(4)
    status_labels = {
        "awaiting_clarification": "等待补充",
        "blocked": "安全阻断",
        "draft": "草稿",
    }
    status_label = status_labels.get(plan.status, plan.status)
    status_col.metric("结果状态", status_label)
    risk_col.metric("风险等级", plan.risk_level.upper())
    confirm_col.metric("人工确认", "必须")
    session_col.metric("会话", plan.session_id[:8])

    if plan.validation_status == "blocked":
        st.error("输出安全验证未通过，具体维修动作已被阻断。")
        for item in plan.validation_errors:
            st.markdown(f"- {item}")
    else:
        st.success("输出安全验证通过")

    if plan.clarification_questions:
        st.warning("现象信息不足，请补充后重新诊断：")
        for question in plan.clarification_questions:
            st.markdown(f"- {question}")
    else:
        st.subheader("已确认事实")
        for item in plan.facts:
            st.markdown(f"- {item}")

        if plan.unknowns:
            with st.expander("未知项与数据缺口", expanded=True):
                for item in plan.unknowns:
                    st.warning(item)
        if plan.conflicts:
            with st.expander("证据冲突", expanded=True):
                for item in plan.conflicts:
                    st.error(item)

        if not plan.corrective_actions:
            if plan.risk_level == "critical":
                st.error("风险达到严重等级，系统已隐藏具体纠正动作，请按现场规程升级处理。")
            else:
                st.warning("当前知识库没有可靠匹配，未生成维修措施。")
        else:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("候选原因（尚未证实）")
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
            title = f"{item.kind}｜{item.source_name}"
            if item.knowledge_id:
                title += f"｜{item.knowledge_id} v{item.source_version}"
            st.markdown(f"**{title}**")
            st.write(item.summary)
            if item.source_url:
                st.markdown(f"[打开来源]({item.source_url}) · {item.source_location}")

    if sessions is not None:
        with st.form("diagnosis_feedback", clear_on_submit=True):
            st.subheader("结果反馈")
            rating_label = st.radio(
                "评价",
                ["有效", "部分有效", "无效", "危险"],
                horizontal=True,
            )
            feedback_comment = st.text_input("说明（可选）")
            feedback_submitted = st.form_submit_button("提交反馈")
        if feedback_submitted:
            rating_map = {
                "有效": "effective",
                "部分有效": "partial",
                "无效": "ineffective",
                "危险": "dangerous",
            }
            try:
                feedback_id = sessions.add_feedback(
                    plan.session_id,
                    rating_map[rating_label],
                    feedback_comment,
                )
            except (ValueError, LookupError) as exc:
                st.error(str(exc))
            else:
                st.success(f"反馈已记录（#{feedback_id}），不会自动修改知识库。")

        if role in {"domain_expert", "administrator"}:
            with st.form("expert_review", clear_on_submit=True):
                st.subheader("专家审核")
                review_status = st.selectbox(
                    "审核结论", ["approved", "needs_revision", "rejected", "unsafe"]
                )
                review_conclusion = st.text_input("复核说明（必填）")
                review_submitted = st.form_submit_button("提交专家审核")
            if review_submitted:
                try:
                    review_id = ExpertReviewService(sessions).submit(
                        access_context, plan.session_id, review_status, review_conclusion
                    )
                except (ValueError, LookupError, PermissionError) as exc:
                    st.error(str(exc))
                else:
                    st.success(f"专家审核已留痕（#{review_id}），与普通反馈分开保存。")

    st.caption("；".join(plan.limitations))

if sessions is not None:
    shadow_report = build_shadow_report(sessions)
    with st.expander("影子试点评测看板", expanded=False):
        st.caption(shadow_report.scope_notice)
        dashboard = st.columns(4)
        dashboard[0].metric("审计会话", shadow_report.total_sessions)
        dashboard[1].metric("工具成功率", f"{shadow_report.tool_success_rate:.1%}")
        dashboard[2].metric("证据覆盖率", f"{shadow_report.evidence_coverage_rate:.1%}")
        dashboard[3].metric("危险反馈", shadow_report.dangerous_feedback_count)
        st.write(
            f"已反馈会话：{shadow_report.reviewed_sessions}｜"
            f"严重风险越界动作：{shadow_report.critical_action_violation_count}"
        )
        st.download_button(
            "导出评测报告 JSON",
            data=json.dumps(shadow_report.to_dict(), ensure_ascii=False, indent=2),
            file_name="shadow_evaluation_report.json",
            mime="application/json",
        )
