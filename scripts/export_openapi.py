"""Export OpenAPI JSON for frontend type sync / contract docs.

Usage:
  poetry run python -m scripts.export_openapi
  poetry run python -m scripts.export_openapi --out frontend/openapi.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("openapi.json"),
        help="Output path (default: ./openapi.json)",
    )
    args = parser.parse_args()

    from app.main import app

    schema = app.openapi()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out} ({len(schema.get('paths') or {})} paths)")


if __name__ == "__main__":
    main()
