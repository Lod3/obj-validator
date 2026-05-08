#!/usr/bin/env python3
"""
build.py - Cross-platform PyInstaller build wrapper for the OBJ validator GUI.

Produces a single-file executable for the host platform:
  - Linux:   dist/validate_obj_gui          (ELF binary)
  - macOS:   dist/validate_obj_gui.app      (app bundle)
  - Windows: dist/validate_obj_gui.exe      (one-file exe)

Run on the platform you want to build for. PyInstaller cannot
cross-compile, so a Windows .exe must be built on Windows, a macOS
.app on macOS, and a Linux binary on Linux.

Usage:
    python build.py
    python build.py --clean      (also wipe build/ and dist/ first)
    python build.py --debug      (keep console window on Windows/macOS,
                                  more verbose PyInstaller output)

Requirements:
  - Python 3.10+
  - PyInstaller 6.x or newer
    Install once via: python -m pip install --user pyinstaller
    Or use a virtual environment (recommended):
      python -m venv .venv-build
      source .venv-build/bin/activate     (Linux/macOS)
      .venv-build\\Scripts\\activate         (Windows)
      pip install pyinstaller

Output goes to ./dist/ next to this script.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ENTRYPOINT = SCRIPT_DIR / "validate_obj_gui.py"
APP_NAME = "validate_obj_gui"
DIST_DIR = SCRIPT_DIR / "dist"
BUILD_DIR = SCRIPT_DIR / "build"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build.py",
        description=(
            "Build a single-file executable of the OBJ validator GUI "
            "for the current platform."
        ),
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove build/ and dist/ directories before building.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help=(
            "Keep the console window on Windows/macOS for debugging, "
            "and pass --log-level=DEBUG to PyInstaller."
        ),
    )
    return parser.parse_args()


def check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "PyInstaller is not installed in this Python environment.\n"
            "Install it first:\n"
            "    python -m pip install pyinstaller\n",
            file=sys.stderr,
        )
        sys.exit(2)


def clean() -> None:
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            print(f"Removing {d}")
            shutil.rmtree(d)


def build_command(debug: bool) -> list[str]:
    """Construct the PyInstaller command for the host platform."""
    cmd: list[str] = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(BUILD_DIR),
    ]

    system = platform.system()
    # On Windows and macOS, --windowed hides the console window so the
    # user does not see a black terminal pop up alongside the GUI.
    # On Linux there is no console-window concept, so the flag is
    # ignored. For debugging we leave the console on.
    if not debug and system in ("Windows", "Darwin"):
        cmd.append("--windowed")

    if debug:
        cmd.extend(["--log-level", "DEBUG"])

    cmd.append(str(ENTRYPOINT))
    return cmd


def main() -> int:
    args = parse_args()

    if not ENTRYPOINT.is_file():
        print(f"Entrypoint not found: {ENTRYPOINT}", file=sys.stderr)
        return 2

    check_pyinstaller()

    if args.clean:
        clean()

    cmd = build_command(args.debug)
    print("Running PyInstaller:")
    print("  " + " ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print(
            f"\nBuild failed with exit code {result.returncode}.",
            file=sys.stderr,
        )
        return result.returncode

    print()
    print(f"Build succeeded. Output in: {DIST_DIR}")
    for item in sorted(DIST_DIR.iterdir()):
        print(f"  {item.name}  ({item.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
