#!/usr/bin/env python3
"""
Build script for bookget exe packages.

Usage:
    python packaging/build.py          # build both
    python packaging/build.py cli      # bookget-cli.exe only
    python packaging/build.py ui       # bookget-ui.exe only (builds frontend first)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    # On Windows, npm is npm.cmd; use shell=True for portability
    result = subprocess.run(cmd, cwd=cwd, shell=(sys.platform == "win32"))
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
    print("\n-- Building bookget-cli.exe --")
    run([
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "cli"),
        "--noconfirm",
        str(PACKAGING / "cli.spec"),
    ])
    print(f"  Output: {DIST / 'bookget-cli.exe'}")


def build_ui() -> None:
    print("\n-- Building bookget-ui.exe --")
    build_frontend()
    run([
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "ui"),
        "--noconfirm",
        str(PACKAGING / "ui.spec"),
    ])
    print(f"  Output: {DIST / 'bookget-ui.exe'}")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    DIST.mkdir(exist_ok=True)

    if target in ("cli", "both"):
        build_cli()
    if target in ("ui", "both"):
        build_ui()

    print("\nDone.")
    for exe in DIST.glob("bookget*.exe"):
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"  {exe.name}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
