"""Validation gate runner over modular policy scanners."""

from __future__ import annotations

from .scanners import ALL_SCANNERS, Scanner, ScannerFinding


def registered() -> tuple[Scanner, ...]:
    return ALL_SCANNERS


def run_all() -> int:
    """Execute all registered scanners; print findings; return exit code."""
    has_error = False
    for scanner in registered():
        print(f"==> scanner: {scanner.name} - {scanner.description}")
        findings = scanner.run()
        if not findings:
            print("    clean")
            continue
        has_error = True
        for f in findings:
            print(f"    ERROR [{f.scanner}] {f.path}:{f.line}: {f.message}")
            if f.hint:
                print(f"          hint: {f.hint}")
    return 1 if has_error else 0


__all__ = ["Scanner", "ScannerFinding", "registered", "run_all"]
