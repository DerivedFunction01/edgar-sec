"""Command-line transport for immutable finalized artifact bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import (
    MANIFEST_DIR,
    create_bundle,
    import_bundle,
    load_manifest,
    prepare_bundle_for_phase,
)
from .paths import resolve_paths
from .registry import ENTRIES


def _interactive() -> int:
    """Run the small menu used by the root launcher."""
    root = Path(resolve_paths().artifacts_root)
    manifest_root = root / MANIFEST_DIR
    manifests = sorted(manifest_root.glob("**/*.json"))
    phases_with_deps = [entry for entry in ENTRIES if entry.dependencies]

    print("\nArtifact bundle options:")
    print("  1. Prepare bundle for a target phase (e.g. Phase 02)")
    print("  2. Create bundle by artifact ID / dataset")
    print("  3. Verify bundle")
    print("  4. Import bundle")
    print("  0. Exit")
    try:
        choice = input("\nChoice [0]: ").strip() or "0"
    except EOFError:
        return 0
    if choice == "0":
        return 0
    if choice == "1":
        if not phases_with_deps:
            print("  no phases currently declare upstream dependencies.")
            return 0
        print("\nTarget phases with upstream dependencies:")
        for index, entry in enumerate(phases_with_deps, start=1):
            reqs = ", ".join(f"{d.phase}/{d.dataset}" for d in entry.dependencies)
            print(f"  {index}. {entry.label} (requires: {reqs})")
        try:
            raw = input(f"Select phase [1-{len(phases_with_deps)}]: ").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= len(phases_with_deps)):
                print("  invalid selection")
                return 0
            selected_entry = phases_with_deps[int(raw) - 1]
            default_out = f"{selected_entry.id.replace('-', '_')}_inputs.bundle.zip"
            output = input(f"Output ZIP [{default_out}]: ").strip() or default_out
            prepare_bundle_for_phase(
                selected_entry.id, artifacts_root=str(root), output=output
            )
            print(f"  bundle created successfully: {output}")
        except (EOFError, OSError, ValueError) as exc:
            print(f"  error: {exc}")
        return 0
    if choice == "2":
        if not manifests:
            print(f"  no artifact manifests found under {manifest_root}")
            return 0
        print("\nAvailable artifacts:")
        for index, path in enumerate(manifests, start=1):
            try:
                value = load_manifest(path)
                print(f"  {index}. {value['artifact_id']} - {value['dataset']}")
            except (OSError, ValueError, KeyError) as exc:
                print(f"  {index}. {path.stem} - invalid manifest ({exc})")
        try:
            selected = input("Artifact numbers or IDs (comma-separated): ").strip()
            output = (
                input("Output ZIP [artifacts.bundle.zip]: ").strip()
                or "artifacts.bundle.zip"
            )
            ids = []
            for item in selected.split(","):
                value = item.strip()
                if value.isdigit() and 1 <= int(value) <= len(manifests):
                    value = manifests[int(value) - 1].stem
                if value:
                    ids.append(value)
            create_bundle(ids, artifacts_root=str(root), output=output)
            print(json.dumps({"bundle": output, "artifacts": ids}, indent=2))
        except (EOFError, OSError, ValueError) as exc:
            print(f"  error: {exc}")
        return 0
    if choice in {"3", "4"}:
        try:
            bundle = input("Bundle path: ").strip()
            if choice == "3":
                import_bundle(bundle, artifacts_root=str(root), verify_hash=True)
                print("  bundle verified")
            else:
                destination = input(f"Artifacts root [{root}]: ").strip() or str(root)
                imported = import_bundle(
                    bundle, artifacts_root=destination, verify_hash=True
                )
                print(json.dumps({"imported": imported}, indent=2))
        except (EOFError, OSError, ValueError) as exc:
            print(f"  error: {exc}")
        return 0
    print("  unknown choice")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) == 1:
        return _interactive()
    parser = argparse.ArgumentParser(prog="artifact-bundle")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--for-phase", required=True, dest="for_phase")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--artifacts-root", default=".artifacts")

    create = commands.add_parser("create")
    create.add_argument("--artifact-id", action="append", required=True)
    create.add_argument("--artifacts-root", default=".artifacts")
    create.add_argument("--output", required=True)
    create.add_argument("--trust-manifests", action="store_true")

    verify = commands.add_parser("verify")
    verify.add_argument("--input", required=True)
    verify.add_argument("--artifacts-root", default=".artifacts")
    verify.add_argument("--hash", action="store_true")

    install = commands.add_parser("import")
    install.add_argument("--input", required=True)
    install.add_argument("--artifacts-root", default=".artifacts")
    install.add_argument("--hash", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare_bundle_for_phase(
            args.for_phase, artifacts_root=args.artifacts_root, output=args.output
        )
    elif args.command == "create":
        create_bundle(
            args.artifact_id,
            artifacts_root=args.artifacts_root,
            output=args.output,
            trust_manifests=args.trust_manifests,
        )
    else:
        import_bundle(
            args.input,
            artifacts_root=args.artifacts_root,
            verify_hash=args.hash or args.command == "import",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
