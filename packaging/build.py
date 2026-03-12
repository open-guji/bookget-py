#!/usr/bin/env python3
"""
Build script for bookget executable packages.

Supports Windows and macOS.

Usage:
    python packaging/build.py          # build both
    python packaging/build.py cli      # bookget-cli only
    python packaging/build.py ui       # bookget-ui only (builds frontend first)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"

IS_WIN = sys.platform == "win32"
EXE_SUFFIX = ".exe" if IS_WIN else ""


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, shell=IS_WIN)
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_frontend() -> None:
    print("\n-- Building frontend (bookget-ui npm) --")
    ui_dir = ROOT / "ui"
    if not (ui_dir / "node_modules").exists():
        run(["npm", "install"], cwd=ui_dir)
    run(["npm", "run", "build:app"], cwd=ui_dir)
    dist_app = ROOT / "ui" / "dist-app"
    print(f"  Frontend built: {dist_app}")


def build_cli() -> None:
    name = f"bookget-cli{EXE_SUFFIX}"
    print(f"\n-- Building {name} --")
    run([
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "cli"),
        "--noconfirm",
        str(PACKAGING / "cli.spec"),
    ])
    print(f"  Output: {DIST / name}")


def build_ui() -> None:
    name = f"bookget-ui{EXE_SUFFIX}"
    print(f"\n-- Building {name} --")
    build_frontend()
    run([
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "ui"),
        "--noconfirm",
        str(PACKAGING / "ui.spec"),
    ])
    print(f"  Output: {DIST / name}")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    DIST.mkdir(exist_ok=True)

    if target in ("cli", "both"):
        build_cli()
    if target in ("ui", "both"):
        build_ui()

    print("\nDone.")
    for f in sorted(DIST.glob("bookget*")):
        if f.suffix in ("", ".exe"):
            size_mb = f.stat().st_size / 1024 / 1024
            print(f"  {f.name}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
