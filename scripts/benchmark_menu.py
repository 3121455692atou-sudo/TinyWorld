#!/usr/bin/env python3
"""Measure the same four-resident menu in this or another checkout.

    uv run python scripts/benchmark_menu.py
    uv run python scripts/benchmark_menu.py /tmp/tinyworld-baseline

The first sample is cold; medians exclude it. Timing is informational, never a
CI threshold. Only an in-memory SQLite database and temporary config are used.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--rounds", type=int, default=9)
    args = parser.parse_args()
    if args.rounds < 2:
        parser.error("at least two rounds are required: one cold and one warm")
    checkout = args.checkout.resolve()
    if not (checkout / "backend/app/tests/conftest.py").is_file():
        parser.error("checkout must contain backend/app/tests/conftest.py")
    sys.path[:0] = [str(checkout / "backend"), str(checkout / "backend/app/tests")]

    with TemporaryDirectory(prefix="tinyworld-menu-benchmark-") as directory:
        os.environ["TLW_CONFIG"] = str(Path(directory) / "unused-config.yaml")
        os.environ["TLW_DATABASE_URL"] = "sqlite:///:memory:"
        from sqlalchemy import event
        from app.core import database
        from app.llm.action_options import build_action_options
        from app.tools.registry import available_tools
        from app.world.visibility import build_visible_people
        from conftest import make_world

        database.configure_database("sqlite:///:memory:")
        database.init_db(drop=True)
        samples = []
        counts: Counter[str] = Counter()

        def count_statements(_connection, _cursor, statement, _parameters, _context, _executemany):
            counts["sql"] += 1
            if statement.lstrip().upper().startswith("SELECT"):
                counts["selects"] += 1

        try:
            with database.SessionLocal() as session:
                world, agents = make_world(session, agent_count=4)
                actor = agents[0]
                session.commit()
                refs = {person.visible_ref: person.target_agent_id for person in build_visible_people(session, actor, 0, persist=False)}
                event.listen(database.engine, "before_cursor_execute", count_statements)
                try:
                    for _ in range(args.rounds):
                        counts.clear()
                        start = perf_counter()
                        specs = available_tools(actor, actor.location.location, session=session)
                        options = build_action_options(session, world, actor, specs, refs)
                        samples.append({**counts, "ms": round((perf_counter() - start) * 1000, 3), "specs": len(specs), "options": len(options)})
                finally:
                    event.remove(database.engine, "before_cursor_execute", count_statements)
                print(json.dumps({
                    "checkout": str(checkout), "residents": len(agents),
                    "location": actor.location.location_id, "rounds": samples,
                    "warm_median_ms": median(row["ms"] for row in samples[1:]),
                    "warm_selects": median(row["selects"] for row in samples[1:]),
                }, ensure_ascii=False))
        finally:
            database.engine.dispose()


if __name__ == "__main__":
    main()
