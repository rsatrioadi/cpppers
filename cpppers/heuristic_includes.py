"""Heuristic include-path inference for no-CDB mode.

When running without a compile_commands.json, libclang can only resolve
``#include`` directives if the right ``-I`` paths are on the command line.
This module fills that gap with two layers:

1. ``sweep_header_dirs`` — walks the project tree once and returns every
   directory that contains at least one header file.  Adding all of them as
   ``-I`` flags covers the common "flat" or "src/include" layout cheaply.

2. ``infer_include_dirs_for_files`` — does a fast regex scan of each source
   file to find the ``#include`` directives it contains, then tries to
   resolve each include path to a real file in the project, and collects
   the parent directories.  This produces per-file augmented ``-I`` lists
   that catch includes that wouldn't be resolved by the global sweep alone
   (e.g. deep sub-trees, generated sub-directories).
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from pathlib import Path

from .defaults import ALL_HEADER_EXTS

log = logging.getLogger(__name__)

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.MULTILINE)


def sweep_header_dirs(source_files: list[str], input_dir: str) -> list[str]:
    """Return every directory under *input_dir* that contains a header file.

    The result is deduplicated and sorted for determinism.  Only directories
    that actually exist at call time are included.
    """
    seen: set[str] = set()
    header_exts = ALL_HEADER_EXTS

    for dirpath, _dirnames, filenames in os.walk(input_dir):
        for fname in filenames:
            if Path(fname).suffix.lower() in header_exts:
                norm = os.path.normpath(dirpath)
                if norm not in seen:
                    seen.add(norm)
                break  # one header is enough to qualify this dir

    return sorted(seen)


def build_header_map(source_files: list[str]) -> dict[str, list[str]]:
    """Build a mapping of *every* include-path suffix that could resolve a file.

    For a file at ``/proj/src/net/socket.h`` the map gets entries:
    - ``"socket.h"`` → [..., ``/proj/src/net/socket.h``]
    - ``"net/socket.h"`` → [..., ``/proj/src/net/socket.h``]

    So both ``#include "socket.h"`` and ``#include "net/socket.h"`` can be
    looked up.  The value is a list because multiple headers can share a
    basename (ambiguous includes — callers should treat those as unresolvable).
    """
    header_exts = ALL_HEADER_EXTS
    mapping: dict[str, list[str]] = defaultdict(list)

    for path in source_files:
        if Path(path).suffix.lower() not in header_exts:
            continue
        norm = os.path.normpath(path)
        p = Path(norm)
        # Walk up to generate all trailing sub-paths up to (but not including)
        # the project root.  We stop at 8 levels to avoid enormous keys.
        parts = p.parts
        for depth in range(1, min(len(parts), 9)):
            suffix = str(Path(*parts[-depth:]))
            mapping[suffix].append(norm)

    return dict(mapping)


def infer_include_dirs_for_files(
    source_files: list[str],
    header_map: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Return per-file lists of extra ``-I`` directories inferred from ``#include`` directives.

    For each source file, the function:
    1. Reads the file text and extracts all ``#include`` paths with a regex.
    2. Looks each one up in *header_map*.
    3. If the lookup is unambiguous (exactly one candidate), records the
       candidate's parent directory as an extra include path for this file.
    4. If ambiguous, logs a debug warning and skips.

    Returns ``{abs_source_path: [extra_include_dir, ...]}``.  Files that
    produce no extra directories are omitted from the result.
    """
    result: dict[str, list[str]] = {}

    for src in source_files:
        try:
            text = Path(src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            log.debug("heuristic_includes: cannot read %s", src)
            continue

        extra_dirs: list[str] = []
        seen_dirs: set[str] = set()

        for match in _INCLUDE_RE.finditer(text):
            inc_path = match.group(1)

            candidates = header_map.get(inc_path) or header_map.get(
                os.path.normpath(inc_path)
            )
            if not candidates:
                continue

            if len(candidates) > 1:
                log.debug(
                    "heuristic_includes: ambiguous include %r in %s (%d candidates) — skipped",
                    inc_path,
                    src,
                    len(candidates),
                )
                continue

            # Resolve the -I root: go up len(inc_path.split('/')) levels from
            # the resolved header so that `#include "net/socket.h"` maps to
            # the directory *above* net/, not to net/ itself.
            depth = len(Path(inc_path).parts)
            parent = Path(candidates[0])
            for _ in range(depth):
                parent = parent.parent
            inc_root = str(parent)

            if inc_root not in seen_dirs:
                seen_dirs.add(inc_root)
                extra_dirs.append(inc_root)

        if extra_dirs:
            result[os.path.normpath(src)] = extra_dirs

    return result
