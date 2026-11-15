"""Assemble the trailforge-tools Lambda package in build/function.

The handler needs app/shop.py beside it. infra/tools.yaml points Code at
build/function. Run from the checkout before packaging the stack:

    python lambda/build.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[1]
OUT = CHECKOUT / "build" / "function"
FILES = (
    CHECKOUT / "lambda" / "handler.py",
    CHECKOUT / "app" / "shop.py",
)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for source in FILES:
        shutil.copy2(source, OUT / source.name)
    print(f"built {OUT.relative_to(CHECKOUT)}: {', '.join(path.name for path in FILES)}")


if __name__ == "__main__":
    main()
