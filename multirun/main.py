from __future__ import annotations

import ast
from importlib.metadata import version
from typing import Any

import click

from multirun import run_multiprocess
from multirun.core import LOG_LEVELS
from multirun.importer import import_from_string, add_cwd_in_path

LEVEL_CHOICES = click.Choice(list(LOG_LEVELS.keys()))

@click.command()
@click.argument("func")
@click.version_option(version("pymultirun"), "-V", "-v", "--version")
@click.option("--workers", type=int, default=1, help="Number of workers to run.", show_default=True,)
@click.option("--timeout", type=float, default=5, help="Timeout for each worker.", show_default=True,)
@click.option("--log-level", type=LEVEL_CHOICES, default=None, help="Log level. [default: info]", show_default=True,)
@click.option("--args", multiple=True, help="Arguments to pass to the function.",)
@click.option("--kwargs", type=(str, str), multiple=True, help="Keyword arguments to pass to the function.", )
def main(
        func: str,
        workers: int,
        timeout: int,
        log_level: str,
        args: tuple[str, ...],
        kwargs: dict[str, Any],
):
    processed_args = []
    for arg in args:
        try:
            processed_args.append(ast.literal_eval(arg))
        except (ValueError, SyntaxError):
            processed_args.append(arg)

    processed_kwargs = {}
    for k, v in kwargs:
        try:
            processed_kwargs[k] = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            processed_kwargs[k] = v

    with add_cwd_in_path():
        run_multiprocess(
            target=import_from_string(func),
            workers=workers,
            timeout=timeout,
            log_level=log_level,
            args=tuple(processed_args),
            kwargs=processed_kwargs,
        )

if __name__ == '__main__':
    main()
