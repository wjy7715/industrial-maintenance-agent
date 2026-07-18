from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agents import MaintenanceOrchestrator
from .data_import import profile_ai4i
from .domain import DiagnosisRequest
from .evaluation import run_retrieval_evaluation


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="工业运维 Agent")
    commands = root.add_subparsers(dest="command", required=True)
    diagnose = commands.add_parser("diagnose")
    diagnose.add_argument("--equipment-id", required=True)
    diagnose.add_argument("--symptom", action="append", required=True)
    commands.add_parser("evaluate")
    profile = commands.add_parser("profile-ai4i")
    profile.add_argument("--file", default="data/raw/ai4i/ai4i2020.csv")
    return root


def main() -> None:
    args = parser().parse_args()
    project = Path(__file__).resolve().parents[2]
    if args.command == "diagnose":
        plan = MaintenanceOrchestrator.from_project(project).diagnose(
            DiagnosisRequest(args.equipment_id, tuple(args.symptom))
        )
        result = plan.to_dict()
    elif args.command == "evaluate":
        result = run_retrieval_evaluation(project).to_dict()
    else:
        path = Path(args.file)
        if not path.is_absolute():
            path = project / path
        result = profile_ai4i(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
