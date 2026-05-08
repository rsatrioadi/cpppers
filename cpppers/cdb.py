"""Compile-database loading and per-file argument resolution.

§3.4: ``compile_commands.json`` is loaded via
``clang.cindex.CompilationDatabase.fromDirectory(<build-dir>)``;
per-file flags via ``getCompileCommands(file_path)``.

This module wraps that with three jobs:
1. Locate the CDB file (``<input>/build/compile_commands.json`` is the
   default; ``--compile-commands-dir`` overrides).
2. Filter args we should *not* pass to ``index.parse()`` — the leading
   compiler executable, the input source filename, and ``-o<output>``.
3. Provide a no-CDB fallback that synthesises ``-x c/c++ -std=c++NN``
   per file extension (per open-question 3 in the recommendation).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .defaults import (
    ALL_HEADER_EXTS,
    ALL_SOURCE_EXTS,
    CPP_HEADER_EXTS,
    CPP_SOURCE_EXTS,
    DEFAULT_CXX_STD,
)


@dataclass
class FileCommand:
    """One translation unit's worth of parse arguments.

    ``filename`` is the absolute source path libclang should parse;
    ``arguments`` are the args to pass to ``Index.parse`` (with the
    compiler executable and the source file itself stripped — libclang
    expects them removed).
    """

    filename: str
    directory: str
    arguments: list[str]


def find_compile_commands(
    input_dir: str | os.PathLike[str],
    *,
    explicit_cdb_dir: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Locate ``compile_commands.json``.

    Search order:
    1. ``explicit_cdb_dir`` if set (must be a directory containing the file).
    2. ``<input_dir>/build/compile_commands.json``.
    3. ``<input_dir>/compile_commands.json``.

    Returns the path if found, else ``None``.
    """
    if explicit_cdb_dir is not None:
        p = Path(explicit_cdb_dir) / "compile_commands.json"
        return p if p.is_file() else None

    root = Path(input_dir)
    for candidate in (root / "build" / "compile_commands.json",
                      root / "compile_commands.json"):
        if candidate.is_file():
            return candidate
    return None


def _strip_args(arguments: list[str], source_file: str) -> list[str]:
    """Remove the compiler executable, the source file, and any ``-o`` pair.

    libclang's ``Index.parse(filename, args=...)`` wants ``args`` to
    *not* contain the source filename or the compiler path, otherwise
    it ends up in the wrong slot or produces "argument unused" diagnostics.
    """
    if not arguments:
        return []

    cleaned: list[str] = []
    skip_next = False
    # Drop arg[0] — that's the compiler executable.
    src = Path(source_file).name
    for i, a in enumerate(arguments):
        if i == 0:
            continue
        if skip_next:
            skip_next = False
            continue
        if a == "-o":
            skip_next = True
            continue
        if a.startswith("-o") and len(a) > 2:
            continue
        # Drop the source file argument however it shows up.
        if a == source_file or os.path.basename(a) == src or a.endswith(src):
            continue
        cleaned.append(a)
    return cleaned


def load_cdb_entries(cdb_path: str | os.PathLike[str]) -> list[FileCommand]:
    """Parse ``compile_commands.json`` and return cleaned entries.

    We do this in pure Python rather than ``clang.cindex.CompilationDatabase``
    so the loader can be tested without libclang being importable.
    """
    raw = json.loads(Path(cdb_path).read_text(encoding="utf-8"))
    out: list[FileCommand] = []
    for entry in raw:
        filename = entry.get("file")
        directory = entry.get("directory") or "."
        if filename is None:
            continue
        # An entry has either "arguments" (list) or "command" (string).
        if "arguments" in entry and entry["arguments"] is not None:
            args = list(entry["arguments"])
        else:
            cmd = entry.get("command", "")
            args = _split_command_string(cmd)
        # Resolve the source path against the entry's working directory
        # so caller code never has to think about that.
        abs_source = (
            filename if os.path.isabs(filename) else str(Path(directory) / filename)
        )
        out.append(
            FileCommand(
                filename=os.path.normpath(abs_source),
                directory=str(Path(directory).resolve()),
                arguments=_strip_args(args, abs_source),
            )
        )
    return out


def _split_command_string(cmd: str) -> list[str]:
    """Naive shell-style split for compile-command-as-string entries.

    Most tools (CMake, Bear) emit the ``arguments`` form already; this
    is just a fallback for the legacy ``command`` form.
    """
    import shlex

    return shlex.split(cmd) if cmd else []


def fallback_args_for_file(
    path: str | os.PathLike[str],
    *,
    cxx_std: str = DEFAULT_CXX_STD,
    extra_include_dirs: Iterable[str] = (),
) -> list[str]:
    """Synthesise minimal parse args for a file when no CDB is available.

    Per open-question 3 of the recommendation: default ``-std=c++20``
    when running C++ sources without a compile database. C inputs get
    ``-x c -std=c11``.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    is_cpp = suffix in CPP_SOURCE_EXTS or suffix in CPP_HEADER_EXTS or suffix in (".hpp", ".h++")
    is_header = suffix in ALL_HEADER_EXTS
    args: list[str] = []
    if is_cpp:
        args += ["-x", "c++-header" if is_header else "c++", f"-std={cxx_std}"]
    elif suffix in ALL_SOURCE_EXTS or suffix == ".h":
        # Plain C path. We treat .h pessimistically as C++ (matches what most
        # IDEs do); pure-C projects will pin it via -x c if they want.
        args += ["-x", "c-header" if is_header else "c", "-std=c11"]
    for inc in extra_include_dirs:
        args += [f"-I{inc}"]
    return args
