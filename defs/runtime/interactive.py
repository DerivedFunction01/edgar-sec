"""Generic partition-oriented interactive runner."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from .partitions import divide_ids_among_workers, parse_id_selection


@dataclass(frozen=True)
class InteractivePhase:
    ensure_plan: Callable[[], dict]
    preview: Callable[[], dict]
    status: Callable[[], dict]
    run_partition: Callable[[int], dict]
    partition_command: Callable[[int], str]


def run_interactive(phase: InteractivePhase, *, default_partition: int = 1) -> int:
    """Run the standard configure-independent partition menu."""
    while True:
        plan = phase.ensure_plan()
        partition_ids = [item["partition_id"] for item in plan.get("partitions", [])]
        if not partition_ids:
            raise ValueError("plan contains no operational partitions")
        print("\nOptions:")
        print("  1. Preview")
        print("  2. Run partition")
        print("  3. Show partition commands")
        print("  4. Show status")
        print("  0. Exit")
        try:
            choice = input("\nChoice [2]: ").strip() or "2"
        except EOFError:
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            try:
                result = phase.preview()
            except (ValueError, FileNotFoundError) as exc:
                print(f"  error: {exc}")
                continue
            print(
                json.dumps(
                    {
                        "sample": len(result.get("sample", [])),
                        "artifact": result.get("sample_artifact"),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            continue
        if choice == "2":
            try:
                selected = parse_id_selection(
                    input(f"Partition ID [{default_partition}]: ").strip()
                    or str(default_partition),
                    partition_ids,
                    "partition",
                )
            except ValueError as exc:
                print(f"  {exc}")
                continue
            for partition_id in selected:
                try:
                    phase.run_partition(partition_id)
                except KeyboardInterrupt:
                    print(
                        "\n  interrupted; completed chunks are preserved and can be resumed"
                    )
                except (ValueError, FileNotFoundError) as exc:
                    print(f"  error: {exc}")
            continue
        if choice == "3":
            try:
                machines = int(input("Number of machines [2]: ").strip() or "2")
                groups = divide_ids_among_workers(partition_ids, machines)
            except ValueError as exc:
                print(f"  {exc}")
                continue
            for machine, ids in enumerate(groups, start=1):
                print(
                    f"\n  machine {machine}: partitions {','.join(map(str, ids)) or '(none)'}"
                )
                for partition_id in ids:
                    print(f"    {phase.partition_command(partition_id)}")
            continue
        if choice == "4":
            print(json.dumps(phase.status(), indent=2, sort_keys=True))
            continue
        print("  unknown choice")


__all__ = ["InteractivePhase", "run_interactive"]
