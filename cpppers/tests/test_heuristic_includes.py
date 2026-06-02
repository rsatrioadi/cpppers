"""Tests for heuristic include-path inference (no-CDB mode)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cpppers.heuristic_includes import (
    build_header_map,
    infer_include_dirs_for_files,
    sweep_header_dirs,
)


def _touch(path: Path, text: str = "") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return os.path.normpath(str(path))


# --- sweep_header_dirs ------------------------------------------------------


def test_sweep_collects_dirs_with_headers(tmp_path):
    h1 = _touch(tmp_path / "include" / "foo.h")
    h2 = _touch(tmp_path / "src" / "net" / "socket.hpp")
    _touch(tmp_path / "src" / "main.cpp")  # no header here directly

    dirs = sweep_header_dirs([h1, h2], str(tmp_path))

    assert os.path.normpath(str(tmp_path / "include")) in dirs
    assert os.path.normpath(str(tmp_path / "src" / "net")) in dirs
    # src/ has no header of its own, only main.cpp
    assert os.path.normpath(str(tmp_path / "src")) not in dirs


def test_sweep_is_sorted_and_deduplicated(tmp_path):
    _touch(tmp_path / "a" / "x.h")
    _touch(tmp_path / "a" / "y.hpp")  # same dir, two headers
    _touch(tmp_path / "b" / "z.h")

    dirs = sweep_header_dirs([], str(tmp_path))

    assert dirs == sorted(dirs)
    assert len(dirs) == len(set(dirs))
    assert len(dirs) == 2


# --- build_header_map -------------------------------------------------------


def test_header_map_indexes_basename_and_subpaths(tmp_path):
    h = _touch(tmp_path / "src" / "net" / "socket.h")

    mapping = build_header_map([h])

    assert mapping["socket.h"] == [h]
    assert mapping[os.path.join("net", "socket.h")] == [h]
    assert mapping[os.path.join("src", "net", "socket.h")] == [h]


def test_header_map_records_ambiguous_basenames(tmp_path):
    a = _touch(tmp_path / "a" / "util.h")
    b = _touch(tmp_path / "b" / "util.h")

    mapping = build_header_map([a, b])

    assert sorted(mapping["util.h"]) == sorted([a, b])
    # But the disambiguated sub-paths stay unique.
    assert mapping[os.path.join("a", "util.h")] == [a]
    assert mapping[os.path.join("b", "util.h")] == [b]


# --- infer_include_dirs_for_files -------------------------------------------


def test_infer_resolves_nested_quoted_include(tmp_path):
    header = _touch(tmp_path / "lib" / "nested" / "types.h")
    src = _touch(
        tmp_path / "src" / "main.cpp",
        '#include "nested/types.h"\nint main() { return 0; }\n',
    )

    mapping = build_header_map([header, src])
    result = infer_include_dirs_for_files([src], mapping)

    # The -I root must be the directory *above* nested/, so that
    # "nested/types.h" resolves.
    assert result[src] == [os.path.normpath(str(tmp_path / "lib"))]


def test_infer_resolves_bare_include(tmp_path):
    header = _touch(tmp_path / "include" / "config.h")
    src = _touch(tmp_path / "main.c", '#include "config.h"\n')

    mapping = build_header_map([header, src])
    result = infer_include_dirs_for_files([src], mapping)

    assert result[src] == [os.path.normpath(str(tmp_path / "include"))]


def test_infer_resolves_angled_include(tmp_path):
    header = _touch(tmp_path / "vendor" / "json.hpp")
    src = _touch(tmp_path / "app.cpp", "#include <json.hpp>\n")

    mapping = build_header_map([header, src])
    result = infer_include_dirs_for_files([src], mapping)

    assert result[src] == [os.path.normpath(str(tmp_path / "vendor"))]


def test_infer_skips_ambiguous_include(tmp_path, caplog):
    a = _touch(tmp_path / "a" / "util.h")
    b = _touch(tmp_path / "b" / "util.h")
    src = _touch(tmp_path / "main.cpp", '#include "util.h"\n')

    mapping = build_header_map([a, b, src])
    with caplog.at_level(logging.DEBUG, logger="cpppers.heuristic_includes"):
        result = infer_include_dirs_for_files([src], mapping)

    # No crash, no entry emitted for the ambiguous-only file.
    assert src not in result
    assert any("ambiguous" in rec.message for rec in caplog.records)


def test_infer_ignores_unknown_system_headers(tmp_path):
    src = _touch(tmp_path / "main.cpp", "#include <vector>\n#include <stdio.h>\n")

    mapping = build_header_map([src])
    result = infer_include_dirs_for_files([src], mapping)

    assert result == {}


def test_infer_deduplicates_repeated_includes(tmp_path):
    header = _touch(tmp_path / "inc" / "a.h")
    src = _touch(
        tmp_path / "main.cpp",
        '#include "a.h"\n#include "a.h"\n',
    )

    mapping = build_header_map([header, src])
    result = infer_include_dirs_for_files([src], mapping)

    assert result[src] == [os.path.normpath(str(tmp_path / "inc"))]
