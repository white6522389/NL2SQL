"""Run the project-specific NL2SQL benchmark against the configured stack."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import create_workflow
from vanna.agents.nl2sql.evaluation import load_eval_cases, run_nl2sql_evaluation


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/nl2sql_cases.yaml")
    parser.add_argument("--output", default="evals/latest_report.json")
    args = parser.parse_args()

    report = await run_nl2sql_evaluation(load_eval_cases(args.dataset), create_workflow)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps(report.metrics(), ensure_ascii=False, indent=2))
    print(f"Detailed report: {output.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
