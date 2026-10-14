"""Console administration for the node. Run ``python -m app.cli``."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> None:
    from app.cli.entry import main as entry

    entry(argv)
