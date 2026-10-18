#!/usr/bin/env python3
"""Run a reproducible offline simulation without reading local provider config.

Examples:
    uv run python scripts/simulate_regression.py --seeds 7 29 101 --rounds 240
    uv run python scripts/simulate_regression.py --modes batch parallel per_agent --rounds 120

The SQLite database lives in a temporary directory and is removed on completion.
No network calls are allowed. A failing invariant exits nonzero with seed/round.
With --output, the report also preserves a small failure snapshot before the
temporary database is removed. It contains no provider configuration or prompts.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 29, 101])
    parser.add_argument("--rounds", type=int, default=120)
    parser.add_argument("--residents", type=int, default=4)
    parser.add_argument("--modes", choices=["batch", "parallel", "per_agent"], nargs="+", default=["batch"])
    parser.add_argument("--malformed-every", type=int, default=17)
    parser.add_argument("--output", type=Path, help="Also save the complete JSON report to this file")
    args = parser.parse_args()
    if args.rounds < 1 or args.residents < 1 or args.malformed_every < 0:
        parser.error("rounds/residents must be positive; malformed-every must be nonnegative")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    with TemporaryDirectory(prefix="tinyworld-regression-") as directory:
        # Configure the app before import, so neither local config nor a user's
        # existing database/providers are touched by this standalone command.
        os.environ["TLW_CONFIG"] = str(Path(directory) / "unused-config.yaml")
        os.environ["TLW_DATABASE_URL"] = f"sqlite:///{Path(directory) / 'simulation.sqlite3'}"
        from app.core import database
        from app.tests.simulation_harness import SimulationFailure, run_simulation

        database.init_db()

        async def run_all() -> None:
            reports = []

            def save_report(failure: dict | None = None) -> None:
                if not args.output:
                    return
                args.output.parent.mkdir(parents=True, exist_ok=True)
                document = {
                    "scope": "Real menus, AOHP parser, validation, effects, scheduler and persistence; deterministic mocked provider, no network. This does not evaluate real LLM decision quality.",
                    "reports": reports,
                }
                if failure is not None:
                    document["failure"] = failure
                args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            for mode in dict.fromkeys(args.modes):
                for seed in dict.fromkeys(args.seeds):
                    start = time.monotonic()
                    try:
                        report = await run_simulation(seed=seed, rounds=args.rounds, residents=args.residents, mode=mode, malformed_every=args.malformed_every)
                    except SimulationFailure as error:
                        save_report(error.diagnostics)
                        if args.output:
                            print(f"Failure diagnostics saved to {args.output}", file=sys.stderr, flush=True)
                        raise
                    summary = {**asdict(report), "wall_seconds": round(time.monotonic() - start, 2)}
                    reports.append(summary)
                    print(json.dumps(summary, ensure_ascii=False), flush=True)
                    save_report()

        try:
            asyncio.run(run_all())
        finally:
            database.engine.dispose()


if __name__ == "__main__":
    main()
