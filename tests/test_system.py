from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from industrial_maintenance_agent import DiagnosisRequest, MaintenanceOrchestrator
from industrial_maintenance_agent.data_import import profile_ai4i
from industrial_maintenance_agent.evaluation import (
    build_shadow_report, run_blind_evaluation, run_retrieval_evaluation,
)
from industrial_maintenance_agent.repositories import (
    EquipmentRepository,
    KnowledgeRepository,
    MaintenanceHistoryCsvRepository,
    SessionRepository,
    TelemetryCsvRepository,
)
from industrial_maintenance_agent.domain import AccessContext, MaintenancePlan
from industrial_maintenance_agent.governance import KnowledgeValidator
from industrial_maintenance_agent.governance import (
    create_sqlite_backup, restore_sqlite_backup, verify_sqlite_backup,
)
from industrial_maintenance_agent.governance.reviews import ExpertReviewService
from industrial_maintenance_agent.safety import (
    MaintenancePlanValidator,
    PlanValidationReport,
    ToolPermissionRegistry,
)
from industrial_maintenance_agent.tools import RiskAssessmentTool, TelemetryTool, execute_tool
from industrial_maintenance_agent.adapters import HermesNarrator


ROOT = Path(__file__).resolve().parents[1]
PUMP_UNITS = {
    "pressure_bar": "bar",
    "vibration_mm_s": "mm/s",
    "temperature_c": "°C",
    "rotation_rpm": "rpm",
}


class DomainTests(unittest.TestCase):
    def test_empty_equipment_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "equipment_id"):
            DiagnosisRequest("", ("振动",))

    def test_empty_symptom_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "故障现象"):
            DiagnosisRequest("PUMP-001", ("",))


class RepositoryTests(unittest.TestCase):
    def test_equipment_list(self) -> None:
        repository = EquipmentRepository(ROOT / "data/sample/equipment.json")
        self.assertEqual(3, len(repository.list_equipment()))

    def test_knowledge_ranking(self) -> None:
        repository = KnowledgeRepository(ROOT / "data/knowledge/pump_troubleshooting.json")
        result = repository.search("centrifugal_pump", "振动和异响")
        self.assertEqual("KB-PUMP-VIBRATION", result[0]["knowledge_id"])

    def test_irrelevant_knowledge_returns_empty(self) -> None:
        repository = KnowledgeRepository(ROOT / "data/knowledge/pump_troubleshooting.json")
        self.assertEqual([], repository.search("centrifugal_pump", "显示器颜色变化"))

    def test_inactive_and_wrong_model_knowledge_is_filtered(self) -> None:
        payload = {
            "metadata": {
                "version": "1.0", "default_status": "active", "review_status": "approved",
                "reviewed_by": "expert-a", "approved_by": "admin-b", "reviewed_at": "2026-07-21",
            },
            "entries": [
                {
                    "knowledge_id": "INACTIVE",
                    "equipment_type": "centrifugal_pump",
                    "status": "retired",
                    "match_terms": {"振动": 5},
                    "summary": "test", "possible_causes": ["test"],
                    "inspection_steps": ["test"], "corrective_actions": ["test"],
                    "safety_warnings": ["test"],
                    "source": {"name": "test", "url": "https://example.com", "location": "test"},
                },
                {
                    "knowledge_id": "MODEL-B",
                    "equipment_type": "centrifugal_pump",
                    "applicable_models": ["MODEL-B"],
                    "match_terms": {"振动": 5},
                    "summary": "test", "possible_causes": ["test"],
                    "inspection_steps": ["test"], "corrective_actions": ["test"],
                    "safety_warnings": ["test"],
                    "source": {"name": "test", "url": "https://example.com", "location": "test"},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            repository = KnowledgeRepository(path)
            self.assertEqual([], repository.search("centrifugal_pump", "振动", equipment_model="MODEL-A"))


class AccessAndGovernanceTests(unittest.TestCase):
    def test_backup_verify_and_safe_restore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assistant.db"
            sessions = SessionRepository(source)
            agent = MaintenanceOrchestrator.from_project(ROOT)
            agent.sessions = sessions
            plan = agent.diagnose(DiagnosisRequest("PUMP-002", ("振动",)))
            backup = create_sqlite_backup(source, root / "backups")
            self.assertTrue(verify_sqlite_backup(Path(backup["manifest_path"]))["valid"])
            restored = root / "restored.db"
            self.assertTrue(restore_sqlite_backup(Path(backup["manifest_path"]), restored)["restored"])
            self.assertIsNotNone(SessionRepository(restored).get_session(plan.session_id))
            with self.assertRaises(FileExistsError):
                restore_sqlite_backup(Path(backup["manifest_path"]), restored)

    def test_tampered_backup_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "assistant.db"
            SessionRepository(source)
            backup = create_sqlite_backup(source, root / "backups")
            path = Path(backup["backup_path"])
            path.write_bytes(path.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "哈希不匹配"):
                verify_sqlite_backup(Path(backup["manifest_path"]))

    def test_site_and_role_are_enforced_before_diagnosis(self) -> None:
        agent = MaintenanceOrchestrator.from_project(ROOT)
        plan = agent.diagnose(
            DiagnosisRequest("PUMP-001", ("振动",)),
            AccessContext("tech-1", "technician", ("demo-site",)),
        )
        self.assertEqual("demo-site", plan.site_id)
        self.assertEqual("tech-1", plan.actor_id)
        for access in (
            AccessContext("admin-1", "knowledge_admin", ("demo-site",)),
            AccessContext("tech-2", "technician", ("other-site",)),
        ):
            with self.assertRaisesRegex(LookupError, "未找到设备或无权访问"):
                agent.diagnose(DiagnosisRequest("PUMP-001", ("振动",)), access)

    def test_current_knowledge_package_passes_governance(self) -> None:
        report = KnowledgeValidator().validate_path(
            ROOT / "data/knowledge/pump_troubleshooting.json",
            AccessContext("expert-1", "domain_expert", ("*",)),
        )
        self.assertTrue(report.valid)
        self.assertEqual(6, report.active_entries)
        self.assertEqual(64, len(report.sha256))

    def test_technician_cannot_validate_knowledge(self) -> None:
        with self.assertRaises(PermissionError):
            KnowledgeValidator().validate_path(
                ROOT / "data/knowledge/pump_troubleshooting.json",
                AccessContext("tech-1", "technician", ("demo-site",)),
            )

    def test_expert_review_is_separate_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionRepository(Path(directory) / "audit.db")
            agent = MaintenanceOrchestrator.from_project(ROOT)
            agent.sessions = sessions
            plan = agent.diagnose(DiagnosisRequest("PUMP-001", ("振动",)))
            review_id = ExpertReviewService(sessions).submit(
                AccessContext("expert-1", "domain_expert", ("demo-site",)),
                plan.session_id, "approved", "证据与步骤已复核",
            )
            detail = sessions.get_session(plan.session_id)
            self.assertEqual(review_id, detail["expert_reviews"][0]["review_id"])
            self.assertEqual("expert-1", detail["expert_reviews"][0]["reviewer_id"])
            with self.assertRaises(PermissionError):
                ExpertReviewService(sessions).submit(
                    AccessContext("tech-1", "technician", ("demo-site",)),
                    plan.session_id, "approved", "越权审核",
                )


class TelemetryCsvRepositoryTests(unittest.TestCase):
    @staticmethod
    def _payload(captured_at: str | None = None) -> bytes:
        captured_at = captured_at or datetime.now(timezone.utc).isoformat()
        return (
            "site_id,equipment_id,equipment_type,equipment_model,captured_at,pressure_bar,"
            "vibration_mm_s,temperature_c,rotation_rpm,active_errors\n"
            f"local-upload,FIELD-PUMP-01,centrifugal_pump,MODEL-A,{captured_at},2.6,4.8,61,1450,"
            "VIBRATION_HIGH\n"
        ).encode("utf-8")

    def test_valid_snapshot_is_read_only_and_traceable(self) -> None:
        repository = TelemetryCsvRepository.from_bytes(self._payload(), "sanitized.csv")
        summary = repository.validation_summary()
        self.assertEqual("valid", summary["status"])
        self.assertFalse(summary["write_back_enabled"])
        self.assertEqual("user_imported_read_only", repository.metadata["kind"])
        self.assertEqual(["FIELD-PUMP-01"], summary["equipment_ids"])

    def test_missing_column_and_duplicate_equipment_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "缺少字段"):
            TelemetryCsvRepository.from_bytes(
                b"equipment_id,captured_at\nP1,2026-01-01T00:00:00Z\n"
            )
        duplicate = self._payload() + self._payload().split(b"\n", 1)[1]
        with self.assertRaisesRegex(ValueError, "设备与采集时间重复"):
            TelemetryCsvRepository.from_bytes(duplicate)

    def test_multiple_points_build_trend_and_latest_snapshot(self) -> None:
        header, row = self._payload().decode("utf-8").splitlines()
        rows: list[str] = []
        for hour, vibration in ((10, 3.0), (11, 4.0), (12, 5.0)):
            parts = row.split(",")
            parts[4] = f"2026-07-21T{hour:02d}:00:00+08:00"
            parts[6] = str(vibration)
            rows.append(",".join(parts))
        repository = TelemetryCsvRepository.from_bytes(
            (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")
        )
        self.assertEqual(3, repository.validation_summary()["rows"])
        self.assertEqual("2026-07-21T12:00:00+08:00", repository.get("FIELD-PUMP-01")["captured_at"])
        trend = repository.trend("FIELD-PUMP-01")
        self.assertEqual("good", trend["status"])
        self.assertEqual("rising", trend["metrics"]["vibration_mm_s"]["direction"])

    def test_naive_timestamp_and_inconsistent_scope_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须包含时区"):
            TelemetryCsvRepository.from_bytes(self._payload("2026-07-21T10:00:00"))
        header, row = self._payload("2026-07-21T10:00:00+08:00").decode("utf-8").splitlines()
        second = row.replace("local-upload", "other-site").replace("10:00:00", "11:00:00")
        with self.assertRaisesRegex(ValueError, "站点、类型或型号"):
            TelemetryCsvRepository.from_bytes((header + "\n" + row + "\n" + second + "\n").encode())

    def test_future_timestamp_is_marked_suspicious(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        repository = TelemetryCsvRepository.from_bytes(self._payload(future))
        result = execute_tool(TelemetryTool(repository), "FIELD-PUMP-01")
        self.assertEqual("suspicious", result.quality)
        self.assertTrue(any("设备时钟" in item for item in result.warnings))

    def test_orchestrator_audits_imported_source_without_claiming_verification(self) -> None:
        repository = TelemetryCsvRepository.from_bytes(self._payload(), "field-export.csv")
        agent = MaintenanceOrchestrator.from_project(ROOT, equipment=repository)
        plan = agent.diagnose(DiagnosisRequest("FIELD-PUMP-01", ("振动",)))
        telemetry = next(item for item in plan.evidence if item.kind == "telemetry")
        self.assertIn("field-export.csv", telemetry.source_name)
        self.assertTrue(any("未独立核验" in item for item in plan.limitations))


class MaintenanceHistoryCsvRepositoryTests(unittest.TestCase):
    def _payload(self) -> bytes:
        return (
            "event_id,equipment_id,event_type,event_at,error_code,action,result,"
            "confirmed_cause,verified_at\n"
            "E1,FIELD-PUMP-01,alarm_open,2026-07-20T09:00:00+08:00,VIBRATION_HIGH,,,,\n"
            "E2,FIELD-PUMP-01,maintenance_closed,2026-07-20T10:00:00+08:00,,"
            "重新对中,振动恢复正常,联轴器偏差,2026-07-20T11:00:00+08:00\n"
            "E3,FIELD-PUMP-01,alarm_close,2026-07-20T11:05:00+08:00,VIBRATION_HIGH,,,,\n"
            "E4,FIELD-PUMP-01,alarm_open,2026-07-21T09:00:00+08:00,VIBRATION_HIGH,,,,\n"
        ).encode("utf-8")

    def test_event_log_builds_current_alarm_and_closed_maintenance(self) -> None:
        repository = MaintenanceHistoryCsvRepository.from_bytes(self._payload(), "history.csv")
        record = repository.get("FIELD-PUMP-01")
        self.assertEqual(["VIBRATION_HIGH"], record["active_errors"])
        self.assertEqual("振动恢复正常", record["maintenance_history"][0]["result"])
        summary = repository.validation_summary()
        self.assertEqual(1, summary["active_alarm_count"])
        self.assertEqual(1, summary["closed_maintenance_count"])
        self.assertFalse(summary["write_back_enabled"])

    def test_duplicate_event_and_naive_timestamp_are_rejected(self) -> None:
        duplicate = self._payload() + self._payload().split(b"\n", 1)[1]
        with self.assertRaisesRegex(ValueError, "事件编号重复"):
            MaintenanceHistoryCsvRepository.from_bytes(duplicate)
        naive = self._payload().replace(
            b"2026-07-20T09:00:00+08:00",
            b"2026-07-20T09:00:00",
            1,
        )
        with self.assertRaisesRegex(ValueError, "必须包含时区"):
            MaintenanceHistoryCsvRepository.from_bytes(naive)

    def test_closed_maintenance_requires_result_and_verification(self) -> None:
        invalid = (
            "event_id,equipment_id,event_type,event_at,error_code,action,result,"
            "confirmed_cause,verified_at\n"
            "E1,P1,maintenance_closed,2026-07-20T10:00:00+08:00,,检查,,,\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "result 为空"):
            MaintenanceHistoryCsvRepository.from_bytes(invalid)
        reversed_time = (
            "event_id,equipment_id,event_type,event_at,error_code,action,result,"
            "confirmed_cause,verified_at\n"
            "E1,P1,maintenance_closed,2026-07-20T10:00:00+08:00,,检查,完成,,"
            "2026-07-20T09:00:00+08:00\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "早于维修事件时间"):
            MaintenanceHistoryCsvRepository.from_bytes(reversed_time)

    def test_orchestrator_uses_independent_history_source_as_evidence(self) -> None:
        telemetry = TelemetryCsvRepository.from_bytes(
            TelemetryCsvRepositoryTests._payload(), "telemetry.csv"
        )
        history = MaintenanceHistoryCsvRepository.from_bytes(self._payload(), "history.csv")
        agent = MaintenanceOrchestrator.from_project(ROOT, equipment=telemetry, history=history)
        plan = agent.diagnose(DiagnosisRequest("FIELD-PUMP-01", ("振动",)))
        evidence = next(item for item in plan.evidence if item.kind == "maintenance_history")
        self.assertIn("history.csv", evidence.source_name)
        self.assertIn("确认原因=联轴器偏差", evidence.summary)
        self.assertTrue(any("故障/维修数据源" in item for item in plan.facts))
        self.assertTrue(any("维修闭环" in item and "未独立核验" in item for item in plan.limitations))


class RiskTests(unittest.TestCase):
    def test_critical_vibration(self) -> None:
        result = RiskAssessmentTool().run(
            "centrifugal_pump", {"vibration_mm_s": 8.6}, PUMP_UNITS
        )
        self.assertEqual("critical", result["level"])
        self.assertIn("mm/s", result["signals"][0])

    def test_normal_values(self) -> None:
        result = RiskAssessmentTool().run(
            "centrifugal_pump",
            {"vibration_mm_s": 2.0, "temperature_c": 45.0},
            PUMP_UNITS,
        )
        self.assertEqual("low", result["level"])

    def test_wrong_units_are_rejected(self) -> None:
        wrong = dict(PUMP_UNITS)
        wrong["vibration_mm_s"] = "inch/s"
        with self.assertRaisesRegex(ValueError, "单位不匹配"):
            RiskAssessmentTool().run("centrifugal_pump", {"vibration_mm_s": 2.0}, wrong)


class ToolContractTests(unittest.TestCase):
    def test_failure_is_structured_instead_of_fabricated(self) -> None:
        class BrokenTool:
            name = "broken"
            version = "9.0"

            def run(self) -> object:
                raise TimeoutError("upstream timeout")

        result = execute_tool(BrokenTool())
        self.assertEqual("failed", result.status)
        self.assertIsNone(result.data)
        self.assertIn("TimeoutError", result.error)
        self.assertEqual("9.0", result.tool_version)

    def test_unregistered_tool_is_denied_before_execution(self) -> None:
        calls = {"count": 0}

        class UnknownTool:
            name = "unknown_external_tool"

            def run(self) -> dict[str, str]:
                calls["count"] += 1
                return {"status": "should_not_run"}

        result = execute_tool(
            UnknownTool(),
            permission_registry=ToolPermissionRegistry(),
        )
        self.assertEqual("failed", result.status)
        self.assertIn("PermissionError", result.error)
        self.assertEqual(0, calls["count"])

    def test_write_requires_confirmation_and_device_control_is_denied(self) -> None:
        registry = ToolPermissionRegistry()
        with self.assertRaisesRegex(PermissionError, "明确确认"):
            registry.authorize("write_cmms_work_order")
        self.assertEqual(
            "confirm",
            registry.authorize("write_cmms_work_order", confirmed=True).decision,
        )
        with self.assertRaisesRegex(PermissionError, "策略禁止"):
            registry.authorize("control_plc", confirmed=True)


class UnitContractTests(unittest.TestCase):
    class Repository:
        metadata = {"kind": "test", "name": "unit-test"}

        def __init__(self, values: dict[str, float]) -> None:
            self.values = values

        def get(self, equipment_id: str) -> dict[str, object]:
            return {
                "equipment_id": equipment_id,
                "equipment_type": "centrifugal_pump",
                "equipment_model": "TEST",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "latest_telemetry": self.values,
            }

        def list_equipment(self) -> list[dict[str, object]]:
            return []

    def test_telemetry_tool_returns_canonical_units(self) -> None:
        values = {
            "pressure_bar": 2.0,
            "vibration_mm_s": 3.0,
            "temperature_c": 50.0,
            "rotation_rpm": 1450.0,
        }
        result = execute_tool(TelemetryTool(self.Repository(values)), "P1")
        self.assertEqual("success", result.status)
        self.assertEqual(PUMP_UNITS, result.data["units"])

    def test_missing_and_out_of_range_metrics_fail_closed(self) -> None:
        missing = {
            "pressure_bar": 2.0,
            "vibration_mm_s": 3.0,
            "temperature_c": 50.0,
        }
        result = execute_tool(TelemetryTool(self.Repository(missing)), "P1")
        self.assertEqual("failed", result.status)
        self.assertIn("遥测缺少指标", result.error)

        invalid = dict(missing, rotation_rpm=-1.0)
        result = execute_tool(TelemetryTool(self.Repository(invalid)), "P1")
        self.assertEqual("failed", result.status)
        self.assertIn("超出允许范围", result.error)


class OutputValidatorTests(unittest.TestCase):
    def test_action_without_knowledge_evidence_is_rejected(self) -> None:
        plan = MaintenancePlan(
            equipment_id="P1",
            equipment_type="centrifugal_pump",
            request_id="R1",
            facts=["fact"],
            corrective_actions=["更换部件"],
            safety_warnings=["人工确认"],
        )
        report = MaintenancePlanValidator().validate(plan)
        self.assertFalse(report.valid)
        self.assertTrue(any("缺少维修知识证据" in item for item in report.errors))

    def test_rejected_output_is_blocked_and_actions_removed(self) -> None:
        class RejectingValidator:
            version = "test"

            def validate(self, plan: MaintenancePlan) -> PlanValidationReport:
                return PlanValidationReport(False, ("测试阻断",))

        base = MaintenanceOrchestrator.from_project(ROOT)
        agent = MaintenanceOrchestrator(
            base.telemetry,
            base.history,
            base.knowledge,
            base.risk,
            validator=RejectingValidator(),
        )
        plan = agent.diagnose(DiagnosisRequest("PUMP-002", ("振动",)))
        self.assertEqual("blocked", plan.status)
        self.assertEqual("blocked", plan.validation_status)
        self.assertEqual([], plan.corrective_actions)
        self.assertTrue(plan.requires_human_confirmation)
        self.assertEqual("failed", plan.tool_trace[-1].status)

    def test_validator_exception_fails_closed(self) -> None:
        class BrokenValidator:
            def validate(self, plan: MaintenancePlan) -> PlanValidationReport:
                raise RuntimeError("validator unavailable")

        base = MaintenanceOrchestrator.from_project(ROOT)
        agent = MaintenanceOrchestrator(
            base.telemetry,
            base.history,
            base.knowledge,
            base.risk,
            validator=BrokenValidator(),
        )
        plan = agent.diagnose(DiagnosisRequest("PUMP-002", ("振动",)))
        self.assertEqual("blocked", plan.status)
        self.assertEqual([], plan.corrective_actions)
        self.assertIn("RuntimeError", plan.validation_errors[0])


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = MaintenanceOrchestrator.from_project(ROOT)

    def test_multitool_plan_is_cited_draft(self) -> None:
        plan = self.agent.diagnose(DiagnosisRequest("PUMP-002", ("振动且压力下降",)))
        self.assertEqual("draft", plan.status)
        self.assertTrue(plan.requires_human_confirmation)
        self.assertEqual(5, len(plan.tool_trace))
        self.assertGreaterEqual(len(plan.evidence), 3)
        self.assertTrue(all(item.source_name for item in plan.evidence))
        self.assertGreaterEqual(len(plan.corrective_actions), 6)
        self.assertTrue(any(item.kind == "maintenance_knowledge" for item in plan.evidence))
        self.assertTrue(plan.request_id)
        self.assertTrue(plan.session_id)
        self.assertTrue(plan.facts)
        self.assertTrue(all(item.version for item in plan.tool_trace))
        self.assertEqual("passed", plan.validation_status)
        self.assertEqual("success", plan.tool_trace[-1].status)
        self.assertTrue(any("mm/s" in item for item in plan.facts))

    def test_unknown_equipment_explicit(self) -> None:
        with self.assertRaisesRegex(LookupError, "未找到设备"):
            self.agent.diagnose(DiagnosisRequest("UNKNOWN", ("振动",)))

    def test_no_match_does_not_invent_action(self) -> None:
        plan = self.agent.diagnose(DiagnosisRequest("PUMP-002", ("显示器颜色变化",)))
        self.assertEqual([], plan.corrective_actions)
        self.assertTrue(any("没有可靠匹配" in item for item in plan.limitations))

    def test_high_risk_has_escalation_warning(self) -> None:
        plan = self.agent.diagnose(DiagnosisRequest("PUMP-003", ("轴承温度持续升高",)))
        self.assertEqual("critical", plan.risk_level)
        self.assertTrue(any("专业人员" in item for item in plan.safety_warnings))
        self.assertEqual([], plan.corrective_actions)
        self.assertTrue(any("隐藏具体纠正动作" in item for item in plan.limitations))

    def test_conflicting_alarm_and_telemetry_is_exposed(self) -> None:
        base = self.agent.telemetry.repository.get("PUMP-001")
        original = base["latest_telemetry"]["vibration_mm_s"]
        base["latest_telemetry"]["vibration_mm_s"] = 2.0
        try:
            plan = self.agent.diagnose(DiagnosisRequest("PUMP-001", ("振动",)))
        finally:
            base["latest_telemetry"]["vibration_mm_s"] = original
        self.assertTrue(any("告警显示振动过高" in item for item in plan.conflicts))

    def test_ambiguous_symptom_requests_clarification(self) -> None:
        plan = self.agent.diagnose(DiagnosisRequest("PUMP-001", ("异常",)))
        self.assertEqual("awaiting_clarification", plan.status)
        self.assertLessEqual(len(plan.clarification_questions), 3)
        self.assertEqual([], plan.corrective_actions)

    def test_history_failure_degrades_without_fabricating_history(self) -> None:
        class BrokenHistory:
            name = "query_fault_history"
            version = "test"

            def run(self, equipment_id: str) -> object:
                raise TimeoutError(equipment_id)

        agent = MaintenanceOrchestrator(
            self.agent.telemetry,
            BrokenHistory(),
            self.agent.knowledge,
            self.agent.risk,
        )
        plan = agent.diagnose(DiagnosisRequest("PUMP-001", ("振动",)))
        history_trace = next(item for item in plan.tool_trace if item.tool == "query_fault_history")
        self.assertEqual("failed", history_trace.status)
        self.assertTrue(any("历史查询失败" in item for item in plan.unknowns))


class SessionRepositoryTests(unittest.TestCase):
    def test_session_and_feedback_are_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionRepository(Path(directory) / "audit.db")
            base = MaintenanceOrchestrator.from_project(ROOT)
            agent = MaintenanceOrchestrator(
                base.telemetry, base.history, base.knowledge, base.risk, sessions=sessions
            )
            request = DiagnosisRequest("PUMP-002", ("压力下降",))
            plan = agent.diagnose(request)
            recent = sessions.recent_sessions()
            self.assertEqual(plan.session_id, recent[0]["session_id"])
            feedback_id = sessions.add_feedback(plan.session_id, "partial", "需补充趋势")
            self.assertGreater(feedback_id, 0)
            feedback = sessions.feedback_for_session(plan.session_id)
            self.assertEqual("partial", feedback[0]["rating"])
            detail = sessions.get_session(plan.session_id)
            self.assertEqual(request.request_id, detail["request_id"])
            self.assertEqual("partial", detail["feedback"][0]["rating"])

    def test_feedback_rejects_unknown_session_and_rating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionRepository(Path(directory) / "audit.db")
            with self.assertRaises(ValueError):
                sessions.add_feedback("missing", "liked")
            with self.assertRaises(LookupError):
                sessions.add_feedback("missing", "effective")

    def test_audit_permission_denial_is_visible_and_prevents_write(self) -> None:
        class DenyAuditRegistry(ToolPermissionRegistry):
            def authorize(self, tool_name: str, confirmed: bool = False):
                if tool_name == "record_audit":
                    raise PermissionError("audit denied for test")
                return super().authorize(tool_name, confirmed)

        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionRepository(Path(directory) / "audit.db")
            base = MaintenanceOrchestrator.from_project(ROOT)
            agent = MaintenanceOrchestrator(
                base.telemetry,
                base.history,
                base.knowledge,
                base.risk,
                permissions=DenyAuditRegistry(),
                sessions=sessions,
            )
            plan = agent.diagnose(DiagnosisRequest("PUMP-002", ("振动",)))
            self.assertEqual([], sessions.recent_sessions())
            self.assertEqual("record_audit", plan.tool_trace[-1].tool)
            self.assertEqual("failed", plan.tool_trace[-1].status)


class ShadowEvaluationTests(unittest.TestCase):
    def test_empty_report_is_explicitly_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionRepository(Path(directory) / "audit.db")
            report = build_shadow_report(sessions)
            self.assertEqual(0, report.total_sessions)
            self.assertEqual(0.0, report.tool_success_rate)
            self.assertIn("不代表真实工厂", report.scope_notice)

    def test_report_calculates_safety_and_traceability_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = SessionRepository(Path(directory) / "audit.db")
            base = MaintenanceOrchestrator.from_project(ROOT)
            agent = MaintenanceOrchestrator(
                base.telemetry, base.history, base.knowledge, base.risk, sessions=sessions
            )
            low = agent.diagnose(DiagnosisRequest("PUMP-002", ("压力下降",)))
            critical = agent.diagnose(DiagnosisRequest("PUMP-003", ("轴承温度持续升高",)))
            sessions.add_feedback(low.session_id, "dangerous", "人工复核发现风险")
            report = build_shadow_report(sessions)
            self.assertEqual(2, report.total_sessions)
            self.assertEqual(1, report.reviewed_sessions)
            self.assertEqual(1, report.critical_sessions)
            self.assertEqual(1.0, report.tool_success_rate)
            self.assertEqual(1.0, report.evidence_coverage_rate)
            self.assertEqual(1.0, report.dangerous_feedback_rate)
            self.assertEqual(0, report.critical_action_violation_count)
            self.assertEqual([], critical.corrective_actions)


class EvaluationTests(unittest.TestCase):
    def test_thirty_cases_are_perfect_regression_set(self) -> None:
        report = run_retrieval_evaluation(ROOT)
        self.assertEqual(30, report.total)
        self.assertEqual(1.0, report.top1_accuracy)
        self.assertEqual(0, report.no_match)

    def test_blind_set_has_negative_cases_and_performance_baseline(self) -> None:
        report = run_blind_evaluation(ROOT, repetitions=2)
        self.assertEqual(15, report.total)
        self.assertEqual(1.0, report.accuracy)
        self.assertEqual(0, report.false_positive + report.false_negative + report.wrong_match)
        self.assertGreaterEqual(report.latency_p95_ms, 0.0)
        self.assertGreaterEqual(report.latency_max_ms, report.latency_p50_ms)


class DataImportTests(unittest.TestCase):
    def test_versioned_manifest_shape(self) -> None:
        payload = json.loads((ROOT / "data/manifests/ai4i.json").read_text(encoding="utf-8"))
        self.assertEqual("CC BY 4.0", payload["license"])
        self.assertEqual(10000, payload["profile"]["rows"])

    def test_downloaded_ai4i_profile_when_present(self) -> None:
        path = ROOT / "data/raw/ai4i/ai4i2020.csv"
        if not path.exists():
            self.skipTest("原始数据未下载；可运行 scripts/download_ai4i.py")
        profile = profile_ai4i(path)
        self.assertEqual(10000, profile["rows"])
        self.assertEqual(339, profile["machine_failures"])


class HermesAdapterTests(unittest.TestCase):
    def test_official_aiagent_contract_is_used_without_tool_authority(self) -> None:
        calls: dict[str, object] = {}

        class FakeAgent:
            def __init__(self, **kwargs: object) -> None:
                calls["kwargs"] = kwargs

            def chat(self, message: str) -> str:
                calls["message"] = message
                return "草稿整理完成"

        fake_module = types.SimpleNamespace(AIAgent=FakeAgent)
        with patch.dict(sys.modules, {"run_agent": fake_module}):
            narrator = HermesNarrator("provider:model")
            result = narrator.render({"status": "draft", "requires_human_confirmation": True})

        self.assertEqual("草稿整理完成", result)
        kwargs = calls["kwargs"]
        self.assertTrue(kwargs["quiet_mode"])
        self.assertIn("terminal", kwargs["disabled_toolsets"])
        self.assertIn("不得新增", kwargs["ephemeral_system_prompt"])
        self.assertIn('"status": "draft"', calls["message"])


if __name__ == "__main__":
    unittest.main()
