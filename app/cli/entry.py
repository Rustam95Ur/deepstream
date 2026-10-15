"""Console entrypoint: ``python -m app.cli``."""

from __future__ import annotations

import argparse
import sys

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.cli import cameras, ops, settings, users, webhooks
from app.cli.console import (
    CliError,
    Ctx,
    configure_stdio,
    fail,
    http_detail,
    prepare,
    validation_detail,
)

_EXAMPLES = """
примеры:
  python -m app.cli status
  python -m app.cli cameras list
  python -m app.cli cameras add --name Калитка --uri rtsp://10.0.0.12/stream1
  python -m app.cli settings set max_streams=8 enable_clip_record=true
  python -m app.cli webhooks add --name campus --url https://campus.example/api/v1/incidents/ --login node1
  docker exec -it nexus-deepstream-api python -m app.cli cameras list

Справка в браузере: /cli.html  (файл docs/cli.html)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=(
            "Управление нодой Nexus DeepStream из консоли: камеры, настройки, "
            "webhook, пользователи, лицензия и история. Пишет в ту же базу, что и веб."
        ),
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Печатать результат JSON-ом. Удобно для скриптов",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"nexus-deepstream {__version__}",
    )
    commands = parser.add_subparsers(dest="group", required=True)
    cameras.register(commands)
    settings.register(commands)
    webhooks.register(commands)
    users.register(commands)
    ops.register_status(commands)
    ops.register_worker(commands)
    ops.register_billing(commands)
    ops.register_history(commands)
    return parser


def main(argv: list[str] | None = None) -> None:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = Ctx(as_json=bool(args.json))
    if getattr(args, "action", "") == "delete" and not getattr(args, "yes", False):
        fail(ctx, "Удаление необратимо. Повторите команду с --yes")
    try:
        prepare()
        args.func(ctx, args)
    except CliError as exc:
        fail(ctx, str(exc))
    except HTTPException as exc:
        fail(ctx, http_detail(exc))
    except ValidationError as exc:
        fail(ctx, validation_detail(exc))
    except SQLAlchemyError as exc:
        fail(ctx, f"Ошибка базы: {exc.__class__.__name__}: {exc}")
    except BrokenPipeError:
        raise SystemExit(0) from None
    except KeyboardInterrupt:
        fail(ctx, "прервано", 130)


if __name__ == "__main__":
    main(sys.argv[1:])
