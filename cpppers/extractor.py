"""Top-level extraction pipeline.

Glues together the four phases described in §3.3 of the recommendation:

1. Filesystem walk → Project / Folder / File / contains
2. CDB resolution (or fallback) → per-TU parse args
3. libclang phase 1 (cursor walk → SymbolEntry buffer) +
   phase 2 (USR-keyed Node emission, declares/encloses/encapsulates) +
   phase 2-edges (typed/specializes/overrides/invokes/...)
4. ``#include`` graph

This module is the only place that should call into multiple sub-modules
in a single function — everything below it is independently testable.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .cdb import (
    FileCommand,
    fallback_args_for_file,
    find_compile_commands,
    load_cdb_entries,
)
from .defaults import ALL_C_CPP_EXTS, ALL_SOURCE_EXTS, DEFAULT_CXX_STD
from .edges import emit_semantic_edges
from .fs_walk import discover_source_files, emit_filesystem_hierarchy
from .heuristic_includes import (
    build_header_map,
    infer_include_dirs_for_files,
    sweep_header_dirs,
)
from .includes import emit_include_edges
from .lpg import Graph
from .parsing import make_index, parse_translation_unit
from .walker import emit_symbol_nodes, walk_translation_units
from .halstead import inject_halstead


log = logging.getLogger(__name__)


@dataclass
class ExtractorOptions:
    """All inputs the pipeline needs. Maps 1:1 onto the CLI flags."""

    input_dir: str
    project_name: str
    exclude_globs: list[str] = field(default_factory=list)
    include_external: bool = False
    output_dir: str = "out"
    output_format: str = "cyjson"  # cyjson | graphml | csv
    no_compile_commands: bool = False
    compile_commands_dir: str | None = None
    cxx_std: str = DEFAULT_CXX_STD
    skip_heuristic_includes: bool = False


def extract(options: ExtractorOptions) -> Graph:
    """Run the full extraction pipeline. Returns a populated Graph."""
    root_resolved = str(Path(options.input_dir).resolve())

    # --- Phase 1: filesystem walk ------------------------------------------
    discovered = discover_source_files(
        root_resolved, exclude_globs=options.exclude_globs
    )
    log.info("Discovered %d C/C++ files under %s", len(discovered), root_resolved)

    graph = Graph(options.project_name)
    file_nodes = emit_filesystem_hierarchy(
        graph,
        project_name=options.project_name,
        root=root_resolved,
        files=discovered,
    )

    # --- Phase 2: per-TU parse args (CDB or fallback) ----------------------
    file_commands = _resolve_file_commands(
        discovered=discovered,
        root=root_resolved,
        no_cdb=options.no_compile_commands,
        cdb_dir=options.compile_commands_dir,
        cxx_std=options.cxx_std,
        skip_heuristic_includes=options.skip_heuristic_includes,
    )

    # --- Phase 3: parse + walk ---------------------------------------------
    idx = make_index()
    tus = []
    for cmd in file_commands:
        result = parse_translation_unit(idx, filename=cmd.filename, arguments=cmd.arguments)
        if result.had_fatal:
            log.warning("Fatal diagnostics in %s: %s", cmd.filename, result.diagnostics)
        tus.append(result.tu)

    table = walk_translation_units(
        tus,
        project_root=root_resolved,
        include_external=options.include_external,
        file_paths_in_project={f for f in discovered},
    )
    usr_to_node = emit_symbol_nodes(
        graph, table, project_root=root_resolved, file_nodes=file_nodes
    )

    # --- Phase 3b: type-system + call edges --------------------------------
    emit_semantic_edges(graph, tus, usr_to_node=usr_to_node)

    # --- Phase 4: include graph --------------------------------------------
    emit_include_edges(
        graph,
        tus,
        project_root=root_resolved,
        file_nodes=file_nodes,
        include_external=options.include_external,
    )

    # --- Phase 5: Halstead complexity metrics ------------------------------
    inject_halstead(graph, table, file_nodes)

    return graph


# ----------------------------------------------------------------------------
# CDB resolution.
# ----------------------------------------------------------------------------


def _auto_include_dirs(root: str) -> list[str]:
    """Common include-root locations for header-relative ``#include "foo.h"``.

    Only returns directories that actually exist — keeps the arg list
    short on projects with non-standard layouts.
    """
    candidates = [Path(root), Path(root) / "include", Path(root) / "src"]
    return [str(c) for c in candidates if c.is_dir()]


def _resolve_file_commands(
    *,
    discovered: list[str],
    root: str,
    no_cdb: bool,
    cdb_dir: str | None,
    cxx_std: str,
    skip_heuristic_includes: bool = False,
) -> list[FileCommand]:
    """Match each discovered source file to a parse command.

    Strategy:
    * If ``no_cdb`` is set, synthesise fallback args for every source file
      and emit a prominent warning to stderr (per §3.2 limitation 1). Include
      paths are inferred heuristically (see ``heuristic_includes``) unless
      ``skip_heuristic_includes`` is set.
    * Otherwise, locate the compile_commands.json. If missing, **fail loudly**
      (per §4 q1 — required by default).
    * For files in the discovery set that the CDB doesn't cover (e.g.,
      headers — most CDBs only list .cpp TUs), synthesise fallback args
      so the walker still sees them.
    """
    discovered_set = set(os.path.normpath(p) for p in discovered)

    if no_cdb:
        sys.stderr.write(
            "WARNING: --no-compile-commands enabled. Type resolution will be "
            "incomplete; cross-TU references and macros may be wrong. See "
            "§3.2 of the recommendation.\n"
        )
        # Auto-detect plausible include roots: <input>, <input>/include,
        # <input>/src. Without this, relative includes like
        # ``#include "foo.h"`` fail in fallback mode and the fallback
        # is effectively useless on most real projects.
        auto_includes = _auto_include_dirs(root)

        # Heuristic layers: a global sweep of every directory containing a
        # header, plus per-file include-path inference from a regex scan of
        # the source's own #include directives.
        global_header_dirs: list[str] = []
        per_file_dirs: dict[str, list[str]] = {}
        if not skip_heuristic_includes:
            global_header_dirs = sweep_header_dirs(discovered, root)
            header_map = build_header_map(discovered)
            per_file_dirs = infer_include_dirs_for_files(discovered, header_map)
            log.info(
                "Heuristic include inference: %d header dirs swept, "
                "%d files got per-file include paths",
                len(global_header_dirs),
                len(per_file_dirs),
            )

        return [
            FileCommand(
                filename=p,
                directory=root,
                arguments=fallback_args_for_file(
                    p,
                    cxx_std=cxx_std,
                    extra_include_dirs=[
                        *auto_includes,
                        str(Path(p).parent),
                        *global_header_dirs,
                        *per_file_dirs.get(p, []),
                    ],
                ),
            )
            for p in sorted(discovered_set)
            if Path(p).suffix.lower() in ALL_SOURCE_EXTS
        ]

    cdb_path = find_compile_commands(root, explicit_cdb_dir=cdb_dir)
    if cdb_path is None:
        raise FileNotFoundError(
            "compile_commands.json not found. Either:\n"
            f"  * place it at {Path(root) / 'build' / 'compile_commands.json'} or {Path(root) / 'compile_commands.json'},\n"
            "  * pass --compile-commands-dir <dir>, or\n"
            "  * pass --no-compile-commands (the SABO graph will be partial; type\n"
            "    resolution will be incomplete)."
        )

    cdb_entries = load_cdb_entries(cdb_path)
    by_file: dict[str, FileCommand] = {
        os.path.normpath(e.filename): e for e in cdb_entries
    }

    # Restrict the CDB entries to files that are in our discovery set —
    # avoids parsing files that --exclude removed from the project.
    out: list[FileCommand] = []
    for path in sorted(discovered_set):
        if Path(path).suffix.lower() not in ALL_SOURCE_EXTS:
            # Headers are picked up via #include from real TUs.
            continue
        if path in by_file:
            out.append(by_file[path])
        else:
            # File in the discovery set but not in the CDB (e.g., a new
            # source file CMake hasn't seen yet). Fall back rather than skip.
            log.info("No CDB entry for %s; using fallback args", path)
            out.append(
                FileCommand(
                    filename=path,
                    directory=root,
                    arguments=fallback_args_for_file(path, cxx_std=cxx_std),
                )
            )
    return out
