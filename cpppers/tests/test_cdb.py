"""Tests for compile_commands.json loading and arg-stripping."""

from __future__ import annotations

import json
from pathlib import Path

from cpppers.cdb import (
    fallback_args_for_file,
    find_compile_commands,
    load_cdb_entries,
)


def test_find_cdb_in_build_dir(tmp_path):
    (tmp_path / "build").mkdir()
    cdb = tmp_path / "build" / "compile_commands.json"
    cdb.write_text("[]")
    assert find_compile_commands(tmp_path) == cdb


def test_find_cdb_in_root(tmp_path):
    cdb = tmp_path / "compile_commands.json"
    cdb.write_text("[]")
    assert find_compile_commands(tmp_path) == cdb


def test_find_cdb_explicit_dir_overrides(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "compile_commands.json").write_text("[]")
    other = tmp_path / "alt"
    other.mkdir()
    other_cdb = other / "compile_commands.json"
    other_cdb.write_text("[]")
    assert find_compile_commands(tmp_path, explicit_cdb_dir=other) == other_cdb


def test_find_cdb_missing_returns_none(tmp_path):
    assert find_compile_commands(tmp_path) is None


def test_load_cdb_strips_compiler_and_source_and_o(tmp_path):
    """Verify the three things that must be stripped:
    1. The leading compiler executable.
    2. The source filename.
    3. ``-o<output>`` and the ``-o output`` two-arg form.
    """
    src = tmp_path / "a.cpp"
    src.write_text("int main(){}")
    cdb = tmp_path / "compile_commands.json"
    cdb.write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "a.cpp",
                    "arguments": [
                        "/usr/bin/clang++",
                        "-std=c++20",
                        "-Iinclude",
                        "-DDEBUG=1",
                        "-c",
                        "a.cpp",
                        "-o",
                        "a.o",
                    ],
                },
                {
                    "directory": str(tmp_path),
                    "file": "b.cpp",
                    "command": "/usr/bin/clang++ -std=c++17 -DRELEASE b.cpp -ob.o",
                },
            ]
        )
    )
    entries = load_cdb_entries(cdb)
    assert len(entries) == 2
    assert entries[0].filename.endswith("a.cpp")
    assert "a.cpp" not in entries[0].arguments
    assert "/usr/bin/clang++" not in entries[0].arguments
    assert "-o" not in entries[0].arguments
    assert "a.o" not in entries[0].arguments
    assert "-std=c++20" in entries[0].arguments
    assert "-Iinclude" in entries[0].arguments
    # Command-string form: also stripped.
    assert "b.cpp" not in entries[1].arguments
    assert "/usr/bin/clang++" not in entries[1].arguments
    assert "-ob.o" not in entries[1].arguments
    assert "-std=c++17" in entries[1].arguments


def test_fallback_args_picks_cpp_for_cpp_extensions():
    args = fallback_args_for_file("foo.cpp")
    assert args[:2] == ["-x", "c++"]
    assert any(a.startswith("-std=c++") for a in args)


def test_fallback_args_picks_c_for_c_extensions():
    args = fallback_args_for_file("foo.c")
    assert args[:2] == ["-x", "c"]
    assert "-std=c11" in args


def test_fallback_args_uses_header_lang_for_headers():
    cpp_h = fallback_args_for_file("foo.hpp")
    assert cpp_h[:2] == ["-x", "c++-header"]
    c_h = fallback_args_for_file("foo.h")
    # .h pessimistically treated as C; that's the "every-IDE" behaviour.
    assert c_h[:2] == ["-x", "c-header"]


def test_fallback_args_includes_extra_includes():
    args = fallback_args_for_file("foo.cpp", extra_include_dirs=["/x", "/y"])
    assert "-I/x" in args
    assert "-I/y" in args
