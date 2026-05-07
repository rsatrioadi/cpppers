"""Tests for the filesystem-driven Project/Folder/File hierarchy."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cpppers.fs_walk import discover_source_files, emit_filesystem_hierarchy
from cpppers.lpg import Graph


def _scaffold(tmp_path: Path) -> Path:
    """Build a small project tree with both kept and excluded contents."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main(){return 0;}\n")
    (tmp_path / "src" / "util.h").write_text("#pragma once\n")
    (tmp_path / "include").mkdir()
    (tmp_path / "include" / "api.hpp").write_text("#pragma once\n")
    # Default-excluded directories — must NOT be discovered.
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "obj.cpp").write_text("// generated\n")
    (tmp_path / "CMakeFiles").mkdir()
    (tmp_path / "CMakeFiles" / "stub.cpp").write_text("// stub\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendor.cpp").write_text("// vendor\n")
    # Non-C/C++ files — should be ignored regardless of location.
    (tmp_path / "src" / "README.md").write_text("# readme\n")
    return tmp_path


def test_discover_skips_default_excluded_dirs(tmp_path):
    root = _scaffold(tmp_path)
    files = discover_source_files(root)
    rels = sorted(Path(f).relative_to(root).as_posix() for f in files)
    assert rels == ["include/api.hpp", "src/main.cpp", "src/util.h"]


def test_discover_honours_user_globs(tmp_path):
    root = _scaffold(tmp_path)
    files = discover_source_files(root, exclude_globs=["src/*.h"])
    rels = sorted(Path(f).relative_to(root).as_posix() for f in files)
    assert "src/util.h" not in rels
    assert "src/main.cpp" in rels


def test_emit_hierarchy_creates_project_folders_files(tmp_path):
    root = _scaffold(tmp_path)
    files = discover_source_files(root)
    g = Graph("demo")
    file_map = emit_filesystem_hierarchy(g, project_name="demo", root=root, files=files)

    # Project node present, id = project name.
    assert g.nodes.find_by_id("demo") is not None

    # Root folder node uses "." id (so it doesn't collide with "demo").
    assert g.nodes.find_by_id(".") is not None

    # Child folders use relative posix paths.
    assert g.nodes.find_by_id("src") is not None
    assert g.nodes.find_by_id("include") is not None

    # Files use relative posix paths.
    assert g.nodes.find_by_id("src/main.cpp") is not None
    assert g.nodes.find_by_id("include/api.hpp") is not None

    # No build/CMakeFiles/node_modules nodes leaked through.
    for forbidden in ("build", "CMakeFiles", "node_modules"):
        assert g.nodes.find_by_id(forbidden) is None

    # contains edges form a tree.
    edge_ids = {(e.source_id, e.label, e.target_id) for e in g.edges}
    assert ("demo", "contains", ".") in edge_ids
    assert (".", "contains", "src") in edge_ids
    assert ("src", "contains", "src/main.cpp") in edge_ids
    assert (".", "contains", "include") in edge_ids
    assert ("include", "contains", "include/api.hpp") in edge_ids

    # file_map is keyed by absolute path.
    for abs_path in file_map:
        assert os.path.isabs(abs_path)


def test_emit_hierarchy_is_idempotent_for_same_folder(tmp_path):
    """Two files sharing a folder must not produce two Folder nodes."""
    root = _scaffold(tmp_path)
    (root / "src" / "extra.cpp").write_text("// extra\n")
    files = discover_source_files(root)
    g = Graph("demo")
    emit_filesystem_hierarchy(g, project_name="demo", root=root, files=files)

    src_folders = [n for n in g.nodes if n.id == "src"]
    assert len(src_folders) == 1


def test_emit_hierarchy_skips_files_outside_root(tmp_path):
    """A file living outside the input root must not break extraction.

    We need an actual sibling directory to ``root``, not a file inside
    ``tmp_path``-which-happens-to-be-root.
    """
    root = _scaffold(tmp_path / "project")
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    outside = sibling / "outside.cpp"
    outside.write_text("int x;\n")
    g = Graph("demo")
    files = [*discover_source_files(root), str(outside)]
    emit_filesystem_hierarchy(g, project_name="demo", root=root, files=files)
    # The outside file is silently dropped here; the libclang phase
    # decides whether to emit it as external.
    assert g.nodes.find_by_id("outside.cpp") is None
    # It must not have leaked through under any escape-path id either.
    assert not any("outside.cpp" in n.id for n in g.nodes)
