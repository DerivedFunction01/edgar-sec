"""Command-line transport for immutable finalized artifact bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .artifacts import (
    MANIFEST_DIR,
    create_bundle,
    discover_legacy_manifests,
    import_bundle,
    load_manifest,
)
from .paths import resolve_paths


def _interactive() -> int:
    """Run the small menu used by the root launcher."""
    root = Path(resolve_paths().artifacts_root)
    manifest_root = root / MANIFEST_DIR
    manifests = sorted(manifest_root.glob("*.json"))
    if not manifests:
        legacy = discover_legacy_manifests(artifacts_root=str(root))
        if legacy:
            print(
                f"\nFound {len(legacy)} validated legacy finalized artifact(s) without manifests."
            )
            try:
                answer = input("Create handoff manifests now? [Y/n]: ").strip().lower()
            except EOFError:
                return 0
            if answer in {"", "y", "yes"}:
                discover_legacy_manifests(artifacts_root=str(root), publish=True)
                manifests = sorted(manifest_root.glob("*.json"))
                print(f"  published {len(manifests)} manifest(s) under {manifest_root}")
    print("\nArtifact bundle options:")
    print("  1. Create bundle")
    print("  2. Verify bundle")
    print("  3. Import bundle")
    print("  0. Exit")
    try:
        choice = input("\nChoice [0]: ").strip() or "0"
    except EOFError:
        return 0
    if choice == "0":
        return 0
    if choice == "1":
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
    if choice in {"2", "3"}:
        try:
            bundle = input("Bundle path: ").strip()
            if choice == "2":
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
    if args.command == "create":
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
