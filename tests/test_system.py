from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from industrial_maintenance_agent import DiagnosisRequest, MaintenanceOrchestrator
from industrial_maintenance_agent.data_import import profile_ai4i
from industrial_maintenance_agent.evaluation import run_retrieval_evaluation
from industrial_maintenance_agent.repositories import (
    EquipmentRepository,
    KnowledgeRepository,
    SessionRepository,
)
from industrial_maintenance_agent.tools import RiskAssessmentTool, execute_tool
from industrial_maintenance_agent.adapters import HermesNarrator


ROOT = Path(__file__).resolve().parents[1]


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
            "metadata": {"version": "1.0", "default_status": "active"},
            "entries": [
                {
                    "knowledge_id": "INACTIVE",
                    "equipment_type": "centrifugal_pump",
                    "status": "retired",
                    "match_terms": {"振动": 5},
                },
                {
                    "knowledge_id": "MODEL-B",
                    "equipment_type": "centrifugal_pump",
                    "applicable_models": ["MODEL-B"],
                    "match_terms": {"振动": 5},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            repository = KnowledgeRepository(path)
            self.assertEqual([], repository.search("centrifugal_pump", "振动", equipment_model="MODEL-A"))


class RiskTests(unittest.TestCase):
    def test_critical_vibration(self) -> None:
        result = RiskAssessmentTool().run("centrifugal_pump", {"vibration_mm_s": 8.6})
        self.assertEqual("critical", result["level"])

    def test_normal_values(self) -> None:
        result = RiskAssessmentTool().run(
            "centrifugal_pump", {"vibration_mm_s": 2.0, "temperature_c": 45.0}
        )
        self.assertEqual("low", result["level"])


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


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = MaintenanceOrchestrator.from_project(ROOT)

    def test_multitool_plan_is_cited_draft(self) -> None:
        plan = self.agent.diagnose(DiagnosisRequest("PUMP-002", ("振动且压力下降",)))
        self.assertEqual("draft", plan.status)
        self.assertTrue(plan.requires_human_confirmation)
        self.assertEqual(4, len(plan.tool_trace))
        self.assertGreaterEqual(len(plan.evidence), 3)
        self.assertTrue(all(item.source_name for item in plan.evidence))
        self.assertGreaterEqual(len(plan.corrective_actions), 6)
        self.assertTrue(any(item.kind == "maintenance_knowledge" for item in plan.evidence))
        self.assertTrue(plan.request_id)
        self.assertTrue(plan.session_id)
        self.assertTrue(plan.facts)
        self.assertTrue(all(item.version for item in plan.tool_trace))

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


class EvaluationTests(unittest.TestCase):
    def test_thirty_cases_are_perfect_regression_set(self) -> None:
        report = run_retrieval_evaluation(ROOT)
        self.assertEqual(30, report.total)
        self.assertEqual(1.0, report.top1_accuracy)
        self.assertEqual(0, report.no_match)


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
