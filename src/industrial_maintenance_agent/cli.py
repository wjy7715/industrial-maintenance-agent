from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agents import MaintenanceOrchestrator
from .data_import import profile_ai4i
from .domain import DiagnosisRequest
from .evaluation import build_shadow_report, run_retrieval_evaluation
from .repositories import SessionRepository, TelemetryCsvRepository


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="工业运维 Agent")
    commands = root.add_subparsers(dest="command", required=True)
    diagnose = commands.add_parser("diagnose")
    diagnose.add_argument("--equipment-id", required=True)
    diagnose.add_argument("--symptom", action="append", required=True)
    diagnose.add_argument("--telemetry-csv", help="使用脱敏的只读遥测 CSV 快照")
    commands.add_parser("evaluate")
    profile = commands.add_parser("profile-ai4i")
    profile.add_argument("--file", default="data/raw/ai4i/ai4i2020.csv")
    sessions = commands.add_parser("sessions", help="查看最近本地审计会话")
    sessions.add_argument("--limit", type=int, default=20)
    session = commands.add_parser("session", help="查看单个诊断会话")
    session.add_argument("--session-id", required=True)
    feedback = commands.add_parser("feedback", help="为已审计会话记录人工反馈")
    feedback.add_argument("--session-id", required=True)
    feedback.add_argument(
        "--rating",
        required=True,
        choices=("effective", "partial", "ineffective", "dangerous"),
    )
    feedback.add_argument("--comment", default="")
    shadow = commands.add_parser("shadow-report", help="生成本地影子试点评测摘要")
    shadow.add_argument("--limit", type=int, default=100)
    validate_csv = commands.add_parser("validate-telemetry-csv", help="校验只读遥测 CSV")
    validate_csv.add_argument("--file", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    project = Path(__file__).resolve().parents[2]
    if args.command == "diagnose":
        equipment = None
        if args.telemetry_csv:
            csv_path = Path(args.telemetry_csv)
            if not csv_path.is_absolute():
                csv_path = project / csv_path
            equipment = TelemetryCsvRepository(csv_path)
        plan = MaintenanceOrchestrator.from_project(project, equipment=equipment).diagnose(
            DiagnosisRequest(args.equipment_id, tuple(args.symptom))
        )
        result = plan.to_dict()
    elif args.command == "evaluate":
        result = run_retrieval_evaluation(project).to_dict()
    elif args.command == "profile-ai4i":
        path = Path(args.file)
        if not path.is_absolute():
            path = project / path
        result = profile_ai4i(path)
    elif args.command == "validate-telemetry-csv":
        path = Path(args.file)
        if not path.is_absolute():
            path = project / path
        result = TelemetryCsvRepository(path).validation_summary()
    else:
        sessions = SessionRepository(project / "data" / "runtime" / "assistant.db")
        if args.command == "sessions":
            result = sessions.recent_sessions(args.limit)
        elif args.command == "session":
            result = sessions.get_session(args.session_id)
            if result is None:
                raise SystemExit(f"未找到诊断会话：{args.session_id}")
        elif args.command == "feedback":
            feedback_id = sessions.add_feedback(args.session_id, args.rating, args.comment)
            result = {"feedback_id": feedback_id, "session_id": args.session_id, "status": "recorded"}
        else:
            result = build_shadow_report(sessions, args.limit).to_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
