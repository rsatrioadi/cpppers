"""``cpppers`` CLI.

Flag set per §3.3 of the recommendation; mirrors ``csharpers``'s
``Program.cs:19-55``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .defaults import DEFAULT_CXX_STD
from .extractor import ExtractorOptions, extract
from .lpg import CsvCodec, CyJsonCodec, GraphMLCodec


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cpppers",
        description="SABO 2.0 C/C++ source-code extractor (libclang-backed)",
    )
    p.add_argument("input_dir", help="Project root (directory containing C/C++ sources)")
    p.add_argument(
        "--name",
        required=True,
        help="Project name (becomes the Project node id)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Path glob (relative to input_dir) to exclude. Repeatable.",
    )
    p.add_argument(
        "--include-external",
        action="store_true",
        help="Emit symbols/files from outside the input directory (system "
        "headers, vendored deps). Default is to skip external content.",
    )
    p.add_argument(
        "--output-dir",
        default="out",
        help="Directory where the output file(s) will be written (default: ./out)",
    )
    p.add_argument(
        "--format",
        choices=["cyjson", "graphml", "csv"],
        default="cyjson",
        dest="output_format",
        help="Output format (default: cyjson)",
    )
    p.add_argument(
        "--no-compile-commands",
        action="store_true",
        help="Run without compile_commands.json. Type resolution will be "
        "incomplete; a warning is printed.",
    )
    p.add_argument(
        "--compile-commands-dir",
        default=None,
        metavar="DIR",
        help="Directory containing compile_commands.json (default: <input_dir>/build "
        "then <input_dir>).",
    )
    p.add_argument(
        "--std",
        dest="cxx_std",
        default=DEFAULT_CXX_STD,
        help=f"C++ standard for fallback parses (default: {DEFAULT_CXX_STD}). "
        "Only used with --no-compile-commands.",
    )
    p.add_argument(
        "--skip-heuristic-includes",
        action="store_true",
        help="Disable heuristic include-path inference in --no-compile-commands "
        "mode. By default, header directories are swept and #include directives "
        "scanned to reconstruct -I paths; pass this to fall back to the minimal "
        "auto-detected roots only.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v INFO, -vv DEBUG)",
    )
    return p


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    options = ExtractorOptions(
        input_dir=args.input_dir,
        project_name=args.name,
        exclude_globs=list(args.exclude),
        include_external=args.include_external,
        output_dir=args.output_dir,
        output_format=args.output_format,
        no_compile_commands=args.no_compile_commands,
        compile_commands_dir=args.compile_commands_dir,
        cxx_std=args.cxx_std,
        skip_heuristic_includes=args.skip_heuristic_includes,
    )

    try:
        graph = extract(options)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / args.name

    fmt = args.output_format
    if fmt == "cyjson":
        path = base.with_suffix(".json")
        CyJsonCodec.write(graph, path)
    elif fmt == "graphml":
        path = base.with_suffix(".graphml")
        GraphMLCodec.write(graph, path)
    elif fmt == "csv":
        # Write {<name>-nodes.csv, <name>-edges.csv}
        CsvCodec.write(graph, base)
        path = base.with_name(base.name + "-nodes.csv")
    else:  # pragma: no cover — argparse `choices` rules out anything else.
        raise AssertionError(f"unreachable format: {fmt}")

    print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
