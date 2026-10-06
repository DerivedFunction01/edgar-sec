"""Validation gate runner over modular policy scanners."""

from __future__ import annotations

from edgar_sec.foundation.scanners import ALL_SCANNERS, Scanner, ScannerFinding


def registered() -> tuple[Scanner, ...]:
    return ALL_SCANNERS


def run_all() -> int:
    """Execute all registered scanners; print findings; return exit code."""
    results: list[tuple[Scanner, list[ScannerFinding]]] = []
    has_error = False
    for scanner in registered():
        findings = scanner.run()
        results.append((scanner, findings))
        if findings:
            has_error = True

    total = len(results)
    violated = sum(1 for _, fs in results if fs)
    clean = total - violated
    if violated == 0:
        print(f"==> ran {total} checks: {clean} clean")
    else:
        print(f"==> ran {total} checks: {clean} clean, {violated} violated")
        for scanner, findings in results:
            if not findings:
                continue
            for f in findings:
                print(f"    ERROR [{f.scanner}] {f.path}:{f.line}: {f.message}")
                if f.hint:
                    print(f"          hint: {f.hint}")
    return 1 if has_error else 0


__all__ = ["Scanner", "ScannerFinding", "registered", "run_all"]
