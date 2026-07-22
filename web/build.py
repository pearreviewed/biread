"""Assemble the deployable in-browser builder into web/dist/.

Builds the biread wheel and gathers the static files a host needs — the page,
the worker, the wheel, and the fonts. Pyodide itself loads from a CDN, so the
output is a handful of files you can drop on any static host.

    python web/build.py        # -> web/dist/, ready to serve or deploy
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DIST = WEB / "dist"
FONTS = ROOT / "biread" / "assets" / "fonts"
FONT_FILES = ("eb-garamond-400.woff2", "eb-garamond-400-italic.woff2")


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    for stale in DIST.glob("*.whl"):
        stale.unlink()

    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(DIST)],
        check=True,
    )
    wheel = next(DIST.glob("biread-*.whl"), None)
    if wheel is None:
        raise SystemExit("no biread wheel was produced")

    # The worker installs the wheel by exact name; fail loudly if they drift.
    if wheel.name not in (WEB / "worker.js").read_text(encoding="utf-8"):
        raise SystemExit(
            f"worker.js does not reference {wheel.name}. Update its wheel filename "
            f"to match the version in pyproject.toml."
        )

    for name in ("builder.html", "worker.js"):
        shutil.copy2(WEB / name, DIST / name)
    for font in FONT_FILES:
        shutil.copy2(FONTS / font, DIST / font)

    files = sorted(p.name for p in DIST.iterdir())
    print(f"Built {DIST.relative_to(ROOT)}/ — {len(files)} files: {', '.join(files)}")
    print("Try it locally:  python -m http.server -d web/dist   (then open /builder.html)")


if __name__ == "__main__":
    main()
