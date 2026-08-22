#!/usr/bin/env python3
"""CI entrypoint for Task05F evaluator evidence materialization.

This wrapper changes no evaluator formulas, support rules, market shopping,
settlement logic, or outcome usage.  It only makes Polars inspect the complete
list-of-dicts schema when materializing evaluator artifacts, avoiding a
constructor inference failure when early chronological rows are unsupported
(and therefore contain null probability fields) while later rows contain
floats.

The underlying preregistered runner remains the source of evaluator logic.
"""
from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "task05f_evaluator_rebuild_runner.py"

_ORIGINAL_DATAFRAME = pl.DataFrame


def _schema_stable_dataframe(data=None, *args, **kwargs):
    if isinstance(data, list) and (not data or isinstance(data[0], dict)):
        kwargs.setdefault("infer_schema_length", None)
    return _ORIGINAL_DATAFRAME(data, *args, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "task05f_evaluator_rebuild_v1.yaml"),
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    # The runner imports the same already-loaded Polars module object, so this
    # affects DataFrame materialization only; all evaluator math is untouched.
    pl.DataFrame = _schema_stable_dataframe
    sys.argv = [
        str(RUNNER),
        "--config",
        str(args.config),
        "--out",
        str(args.out),
    ]
    runpy.run_path(str(RUNNER), run_name="__main__")


if __name__ == "__main__":
    main()
