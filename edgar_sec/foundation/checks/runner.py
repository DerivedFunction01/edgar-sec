"""Validation gate runner over modular policy scanners."""

from __future__ import annotations

import multiprocessing

from edgar_sec.foundation.scanners import ALL_SCANNERS, Scanner, ScannerFinding


def _run_scanner(index: int) -> tuple[int, list[ScannerFinding]]:
    """Execute one registered scanner in a worker process."""
    from edgar_sec.foundation.scanners import ALL_SCANNERS

    return index, ALL_SCANNERS[index].run()


def registered() -> tuple[Scanner, ...]:
    return ALL_SCANNERS


def run_all() -> int:
    """Execute all registered scanners; print findings; return exit code."""
    scanners = registered()
    total = len(scanners)

    workers = 0
    try:
        from edgar_sec.foundation.runtime.resources import (
            auto_worker_count,
            available_memory_bytes,
        )

        workers = auto_worker_count(available_memory_bytes())
    except Exception:
        workers = 0
    if workers < 2:
        workers = 0
    workers = min(workers, total) if workers else 0

    results_by_index: list[list[ScannerFinding] | None] = [None] * total
    if workers >= 2:
        pool = None
        try:
            pool = multiprocessing.Pool(processes=workers)
        except Exception:
            pool = None
        if pool is None:
            for index in range(total):
                results_by_index[index] = scanners[index].run()
        else:
            try:
                for index, findings in pool.map(_run_scanner, range(total)):
                    results_by_index[index] = findings
            finally:
                pool.close()
                pool.join()
    else:
        for index in range(total):
            results_by_index[index] = scanners[index].run()

    paired: list[tuple[Scanner, list[ScannerFinding]]] = [
        (scanners[index], results_by_index[index] or []) for index in range(total)
    ]

    has_error = False
    for _, findings in paired:
        if findings:
            has_error = True

    violated = sum(1 for _, fs in paired if fs)
    clean = total - violated
    if violated == 0:
        print(f"==> ran {total} checks: {clean} clean")
    else:
        print(f"==> ran {total} checks: {clean} clean, {violated} violated")
        for scanner, findings in paired:
            if not findings:
                continue
            for finding in findings:
                print(
                    f"    ERROR [{finding.scanner}] {finding.path}:{finding.line}: "
                    f"{finding.message}"
                )
                if finding.hint:
                    print(f"          hint: {finding.hint}")
    return 1 if has_error else 0


__all__ = ["Scanner", "ScannerFinding", "registered", "run_all"]
