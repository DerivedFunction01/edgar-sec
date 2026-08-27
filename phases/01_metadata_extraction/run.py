"""Production chunk runner with an optional interactive wizard.

Non-interactive (single chunk, suitable for automation and multi-machine
fan-out):

    python -m phases.01_metadata_extraction.run \
        --input uploads/cik-sec.csv \
        --artifacts .artifacts/metadata/runs/<run-id> \
        --chunk-size 1000 --chunk-id 12 --workers 4

Interactive (no --chunk-id): a wizard similar to init_venv.py that walks
through configuration, can create the plan, and can run:

  1. all remaining chunks on this machine
  2. a division of chunks across N machines (printing the exact command
     for each machine, then executing this machine's share)
  3. explicitly selected chunks (e.g. "1,3,5-8")

All execution still goes through the shared core (build_plan, run_chunk,
get_status); this shim never duplicates fetching, normalization, or
checkpoint logic. Exits nonzero on validation or network failures.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .core import RunOptions, build_plan, get_status, load_plan, run_chunk

log = logging.getLogger("metadata.run")


# ---------------------------------------------------------------------------
# Argument parsing (kept identical to before for the non-interactive path)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phases.01_metadata_extraction.run",
        description="Run one chunk non-interactively, or launch the interactive wizard when --chunk-id is omitted.",
    )
    parser.add_argument("--input", default=RunOptions.input_path)
    parser.add_argument("--artifacts", default=RunOptions.artifacts_dir)
    parser.add_argument("--chunk-size", type=int, default=RunOptions.chunk_size)
    parser.add_argument(
        "--chunk-id",
        type=int,
        default=None,
        help="omit to start the interactive wizard",
    )
    parser.add_argument("--workers", type=int, default=RunOptions.workers)
    parser.add_argument("--timeout", type=float, default=RunOptions.timeout_s)
    parser.add_argument("--max-retries", type=int, default=RunOptions.max_retries)
    parser.add_argument("--rate-limit", type=float, default=RunOptions.rate_limit_rps)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--cache-dir", default="")
    parser.add_argument(
        "--max-failure-attempts",
        type=int,
        default=RunOptions.max_failure_attempts,
        help="independent failed runs after which a URL is skipped without retrying",
    )
    parser.add_argument(
        "--ignore-failure-history",
        action="store_true",
        help="attempt every URL regardless of recorded failures",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--run-id", default="local")
    return parser


def options_from_args(args) -> RunOptions:
    return RunOptions(
        input_path=args.input,
        artifacts_dir=args.artifacts,
        chunk_size=args.chunk_size,
        chunk_id=args.chunk_id,
        workers=args.workers,
        timeout_s=args.timeout,
        max_retries=args.max_retries,
        rate_limit_rps=args.rate_limit,
        user_agent=args.user_agent,
        cache_dir=args.cache_dir,
        max_failure_attempts=args.max_failure_attempts,
        ignore_failure_history=getattr(args, "ignore_failure_history", False),
        limit=args.limit,
        log_level=args.log_level,
        run_id=args.run_id,
    )


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------


def ask(prompt: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_int(prompt: str, default: int, minimum: int = 1) -> int:
    raw = ask(prompt, str(default))
    try:
        value = int(raw)
        if value < minimum:
            raise ValueError
        return value
    except ValueError:
        print(f"  invalid number '{raw}', using {default}")
        return default


def ask_float(prompt: str, default: float, minimum: float = 0.0) -> float:
    raw = ask(prompt, str(default))
    try:
        value = float(raw)
        if value <= minimum:
            raise ValueError
        return value
    except ValueError:
        print(f"  invalid number '{raw}', using {default}")
        return default


def parse_chunk_spec(spec: str, known_ids: list[int]) -> list[int]:
    """Parse '1,3,5-8' into an ordered list of valid chunk ids."""
    known = set(known_ids)
    selected: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            selected.extend(range(start, end + 1))
        else:
            selected.append(int(part))
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError(f"unknown chunk ids: {unknown}")
    return sorted(dict.fromkeys(selected))


def chunk_command(options: RunOptions, chunk_id: int) -> str:
    agent = options.user_agent or "$SEC_USER_AGENT"
    return (
        f".venv/bin/python -m phases.01_metadata_extraction.run"
        f" --input {options.input_path}"
        f" --artifacts {options.artifacts_dir}"
        f" --chunk-id {chunk_id}"
        f" --workers {options.workers}"
        f" --rate-limit {options.rate_limit_rps}"
        f" --user-agent '{agent}'"
    )


def divide_chunks_among_machines(all_ids: list[int], machines: int) -> list[list[int]]:
    """Contiguous, balanced groups of chunk ids, one per machine."""
    groups: list[list[int]] = [[] for _ in range(machines)]
    base, remainder = divmod(len(all_ids), machines)
    index = 0
    for machine in range(machines):
        count = base + (1 if machine < remainder else 0)
        groups[machine] = all_ids[index : index + count]
        index += count
    return groups


def configure_interactively(args) -> RunOptions:
    print("\n" + "=" * 64)
    print("SEC submissions metadata extraction — chunk runner")
    print("=" * 64)
    print("Press Enter to accept the [default] shown for each setting.\n")

    input_path = ask("Input CSV", args.input or RunOptions.input_path)
    artifacts_dir = ask("Artifacts/run directory", args.artifacts or RunOptions.artifacts_dir)
    chunk_size = ask_int("Chunk size (CIKs per chunk)", args.chunk_size)
    workers = ask_int("Concurrent workers", args.workers)
    rate_limit = ask_float("Rate limit (requests/second, per process)", args.rate_limit)
    user_agent = ask(
        "SEC User-Agent 'AppName/1.0 you@example.com'",
        args.user_agent or os.environ.get("SEC_USER_AGENT", ""),
    )
    cache_dir = ask("Optional raw-response cache directory (blank = off)", args.cache_dir)

    options = RunOptions(
        input_path=input_path,
        artifacts_dir=artifacts_dir,
        chunk_size=chunk_size,
        workers=workers,
        rate_limit_rps=rate_limit,
        user_agent=user_agent,
        cache_dir=cache_dir,
        timeout_s=args.timeout,
        max_retries=args.max_retries,
        limit=args.limit,
        log_level=args.log_level,
        run_id=args.run_id,
    )
    options.validate()
    return options


def ensure_plan(options: RunOptions) -> dict:
    try:
        plan = load_plan(options)
        print(f"\nLoaded existing plan: {len(plan['chunks'])} chunks, {plan['row_count']} CIKs")
        return plan
    except (FileNotFoundError, ValueError):
        answer = ask(
            f"No valid plan.json in {options.artifacts_dir}. Create one now? (y/N)",
            "y",
        )
        if answer.strip().lower() not in ("y", "yes"):
            raise SystemExit("aborted: run `plan` first or answer yes to create it")
        plan = build_plan(options)
        print(f"Plan created: {len(plan['chunks'])} chunks, {plan['row_count']} CIKs")
        return plan


def run_selected_chunks(options: RunOptions, chunk_ids: list[int]) -> int:
    """Execute chunks sequentially with resume-aware skipping. Returns an
    exit code: 0 when every chunk succeeded or was already complete."""
    failures: list[tuple[int, str]] = []
    completed = skipped = filings = 0
    for index, chunk_id in enumerate(chunk_ids, start=1):
        print(f"\n[{index}/{len(chunk_ids)}] chunk {chunk_id}")
        print("-" * 48)
        try:
            summary = run_chunk(
                RunOptions(
                    **{**options.to_dict(), "chunk_id": chunk_id, "run_id": options.run_id}
                )
            )
        except KeyboardInterrupt:
            print("\ninterrupted; completed chunks are preserved and can be resumed")
            return 130
        except Exception as exc:  # noqa: BLE001 — one bad chunk must not kill the rest
            failures.append((chunk_id, f"{type(exc).__name__}: {exc}"))
            print(f"  chunk {chunk_id} FAILED: {type(exc).__name__}: {exc}")
            continue
        if summary.get("skipped"):
            skipped += 1
            print(f"  already complete: {summary['checkpoint']}")
        else:
            completed += 1
            filings += summary.get("filings", 0)
            statuses = " ".join(f"{k}={v}" for k, v in sorted(summary["statuses"].items()))
            print(f"  rows={summary['rows']} ({statuses}) filings={summary['filings']}")

    print("\n" + "=" * 64)
    print(f"summary: {completed} executed, {skipped} skipped, {len(failures)} failed, "
          f"{filings} filing records")
    for chunk_id, error in failures:
        print(f"  chunk {chunk_id}: {error}")
    if not failures:
        print(
            "\nnext: merge with\n"
            f"  .venv/bin/python -m phases.01_metadata_extraction.cli merge"
            f" --artifacts {options.artifacts_dir}"
            f" --output phases/01_metadata_extraction/output/merged/submission_metadata.parquet"
        )
    return 1 if failures else 0


def interactive_wizard(args) -> int:
    options = configure_interactively(args)

    while True:
        plan = ensure_plan(options)
        all_ids = [chunk["chunk_id"] for chunk in plan["chunks"]]
        while True:
            status = get_status(options)
            missing = status.get("missing_chunks", [])
            print("\nOptions:")
            print("  1. Run all remaining chunks on this machine"
                  f" ({len(missing)} remaining)")
            print("  2. Divide chunks across N machines (show commands, run this machine's share)")
            print("  3. Run specific chunks (e.g. '1,3,5-8')")
            print("  4. Show status")
            print("  5. Reconfigure settings")
            print("  0. Exit")
            try:
                choice = input("\nChoice [1]: ").strip() or "1"
            except EOFError:
                return 0

            if choice == "0":
                return 0
            if choice == "1":
                code = run_selected_chunks(options, missing)
                if code:
                    return code
                break  # back to ensure_plan/menu; plan is complete now
            if choice == "2":
                machines = ask_int("Number of machines", 2)
                groups = divide_chunks_among_machines(all_ids, machines)
                print("\nRun one command per machine (each re-validates the same plan):")
                for machine, ids in enumerate(groups, start=1):
                    listing = ",".join(str(i) for i in ids) or "(none)"
                    print(f"\n  machine {machine}: chunks {listing}")
                    for chunk_id in ids:
                        print(f"    {chunk_command(options, chunk_id)}")
                share = ask(f"\nWhich machine is THIS one? (1-{machines}, blank = skip)", "")
                if share.strip().isdigit() and 1 <= int(share) <= machines:
                    ids = groups[int(share) - 1]
                    if not ids:
                        print("  that machine has no assigned chunks")
                        continue
                    answer = ask(f"Run chunks {','.join(map(str, ids))} now? (Y/n)", "y")
                    if answer.strip().lower() in ("y", "yes", ""):
                        code = run_selected_chunks(options, ids)
                        if code:
                            return code
                        break
                continue
            if choice == "3":
                spec = ask("Chunk ids (e.g. '1,3,5-8')", "")
                try:
                    ids = parse_chunk_spec(spec, all_ids)
                except ValueError as exc:
                    print(f"  {exc}")
                    continue
                code = run_selected_chunks(options, ids)
                if code:
                    return code
                break
            if choice == "4":
                print_json(status)
                continue
            if choice == "5":
                return interactive_wizard(args)  # restart with fresh prompts
            print("  unknown choice")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    if args.chunk_id is None:
        try:
            return interactive_wizard(args)
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130

    options = options_from_args(args)
    try:
        summary = run_chunk(options)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — network or unexpected failure: nonzero exit
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print_json(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
