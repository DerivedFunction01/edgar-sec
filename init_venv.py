"""Venv setup built from pyproject.toml, the single dependency source."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

VENV_DIR = ".venv"
USE_VENV = True
USE_UV = False
UV_PATH: str | None = None
UPGRADE = False

PROJECT_SPEC = ".[dev]"


def find_uv() -> str | None:
    """Resolve uv: PATH first, then the per-user install locations."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "uv",
        Path.home() / ".cargo" / "bin" / "uv",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def detect_uv() -> bool:
    """Record the resolved uv path, or fall back to pip."""
    global USE_UV, UV_PATH
    UV_PATH = find_uv()
    if UV_PATH is not None:
        try:
            result = subprocess.run(
                [UV_PATH, "--version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print(f"⚡ uv detected ({result.stdout.strip()}) — using uv.")
                USE_UV = True
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    print("   uv not found — falling back to pip.")
    USE_UV = False
    return False


def _pip_executable() -> str:
    """Path to the venv pip (or bare 'pip' when not using a venv)."""
    if not USE_VENV:
        return "pip"
    if sys.platform == "win32":
        return f"{VENV_DIR}\\Scripts\\pip.exe"
    return f"{VENV_DIR}/bin/pip"


def _python_executable() -> str:
    """Path to the venv python (or the current interpreter)."""
    if not USE_VENV:
        return sys.executable
    if sys.platform == "win32":
        return f"{VENV_DIR}\\Scripts\\python.exe"
    return f"{VENV_DIR}/bin/python"


def _build_install_cmd(spec: str) -> list[str]:
    """Build install argv for uv or pip (never a shell string)."""
    if USE_UV:
        cmd = [UV_PATH, "pip", "install"]
        if USE_VENV:
            cmd += ["--python", _python_executable()]
        if UPGRADE:
            cmd.append("--upgrade")
        return cmd + [spec]
    cmd = [_pip_executable(), "install"]
    if UPGRADE:
        cmd.append("--upgrade")
    return cmd + [spec]


def install_project() -> bool:
    """Install this package and its dev set from pyproject.toml."""
    print("📦 Installing edgar-sec from pyproject.toml (runtime + dev)...")
    cmd = _build_install_cmd(PROJECT_SPEC)
    print(f"   Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("✅ Package installed successfully.")
        return True
    print("❌ Package install failed.")
    return False


def install_duckdb_extensions() -> None:
    """Install the DuckDB extensions the codebase relies on."""
    print("📦 Installing DuckDB extensions...")
    code = "import duckdb; duckdb.connect().execute('INSTALL sqlite_scanner')"
    result = subprocess.run([_python_executable(), "-c", code])
    if result.returncode == 0:
        print("✅ DuckDB extensions installed successfully.")
    else:
        print("❌ Failed to install DuckDB extensions.")


def create_venv() -> None:
    """Create the virtual environment if it doesn't exist."""
    venv_path = Path(VENV_DIR)
    if venv_path.exists():
        print(f"✓ Found existing virtual environment: '{VENV_DIR}'")
        return
    print(f"🛠️ Creating virtual environment in '{VENV_DIR}'...")
    try:
        if USE_UV:
            subprocess.run([UV_PATH, "venv", VENV_DIR], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)
        print("✅ Virtual environment created successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to create virtual environment: {e}")
        sys.exit(1)


def check_installation() -> None:
    """Report versions of the declared packages in the venv."""
    print("\n🔍 Checking current installation...")
    python_exec = _python_executable()
    print(f"   Using Python: {python_exec}")
    code = (
        "import importlib.metadata as m\n"
        "for name in ('edgar-sec', 'duckdb', 'pandas', 'polars', 'pyarrow',"
        " 'pymupdf', 'selectolax', 'fastapi', 'requests', 'pytest',"
        " 'pytest-xdist', 'ruff'):\n"
        "    try:\n"
        "        print(f'   {name}: {m.version(name)}')\n"
        "    except m.PackageNotFoundError:\n"
        "        print(f'   {name}: Not installed')\n"
    )
    subprocess.run([python_exec, "-c", code])
    print("\n📦 Checking Parquet support...")
    parquet_code = (
        "import pandas as pd; "
        "pd.io.parquet.get_engine('auto'); "
        "print('✅ Parquet engine available')"
    )
    subprocess.run([python_exec, "-c", parquet_code])


def main() -> None:
    global USE_VENV, UPGRADE

    parser = argparse.ArgumentParser(
        description="Environment setup built from pyproject.toml."
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Install packages in the global environment instead of a venv.",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade packages when installing.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report the installed versions in the venv and exit.",
    )
    args = parser.parse_args()

    if args.no_venv:
        USE_VENV = False
    if args.upgrade:
        UPGRADE = True

    if args.check:
        if USE_VENV and not Path(_python_executable()).is_file():
            print(f"❌ No virtual environment found at '{VENV_DIR}'.")
            sys.exit(1)
        check_installation()
        return

    print("\n🔍 Detecting package manager...")
    detect_uv()

    if USE_VENV:
        create_venv()

    print("\nInstalling edgar-sec (runtime + dev) from pyproject.toml...")
    if not install_project():
        sys.exit(1)
    install_duckdb_extensions()
    print("\n✅ Setup complete!")


if __name__ == "__main__":
    main()
