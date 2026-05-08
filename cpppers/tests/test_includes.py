"""Tests for the ``#include`` graph emitter."""

from __future__ import annotations

from pathlib import Path

import pytest

cindex = pytest.importorskip("clang.cindex")

from cpppers.cdb import fallback_args_for_file
from cpppers.fs_walk import emit_filesystem_hierarchy
from cpppers.includes import emit_include_edges
from cpppers.lpg import Graph
from cpppers.parsing import make_index, parse_translation_unit


def _sources(tmp_path: Path, files: dict[str, str]):
    paths = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        paths.append(p)
    return paths


def test_includes_within_project_emit_edges(tmp_path):
    paths = _sources(
        tmp_path,
        {
            "src/foo.h": "#pragma once\nint foo();\n",
            "src/foo.cpp": '#include "foo.h"\nint foo() { return 0; }\n',
            "src/bar.h": "#pragma once\nint bar();\n",
            "src/bar.cpp": '#include "bar.h"\n#include "foo.h"\nint bar() { return foo(); }\n',
        },
    )
    g = Graph("demo")
    abs_files = [str(p.resolve()) for p in paths]
    file_nodes = emit_filesystem_hierarchy(
        g, project_name="demo", root=tmp_path, files=abs_files
    )

    idx = make_index()
    tus = []
    for p in paths:
        if p.suffix.lower() != ".cpp":
            continue
        args = fallback_args_for_file(p, extra_include_dirs=[str(tmp_path / "src")])
        result = parse_translation_unit(idx, filename=p, arguments=args)
        assert not result.had_fatal, result.diagnostics
        tus.append(result.tu)

    emit_include_edges(
        g, tus, project_root=str(tmp_path), file_nodes=file_nodes, include_external=False
    )

    triples = {(e.source_id, e.label, e.target_id) for e in g.edges if e.label == "includes"}
    assert ("src/foo.cpp", "includes", "src/foo.h") in triples
    assert ("src/bar.cpp", "includes", "src/bar.h") in triples
    assert ("src/bar.cpp", "includes", "src/foo.h") in triples


def test_includes_dedup_across_translation_units(tmp_path):
    """If two TUs both include foo.h, we still emit only one edge per (src, dst)."""
    paths = _sources(
        tmp_path,
        {
            "src/foo.h": "#pragma once\n",
            "src/a.cpp": '#include "foo.h"\nint a();\n',
            "src/b.cpp": '#include "foo.h"\nint b();\n',
        },
    )
    g = Graph("demo")
    abs_files = [str(p.resolve()) for p in paths]
    file_nodes = emit_filesystem_hierarchy(
        g, project_name="demo", root=tmp_path, files=abs_files
    )
    idx = make_index()
    tus = [
        parse_translation_unit(
            idx,
            filename=p,
            arguments=fallback_args_for_file(p, extra_include_dirs=[str(tmp_path / "src")]),
        ).tu
        for p in paths
        if p.suffix.lower() == ".cpp"
    ]
    emit_include_edges(
        g, tus, project_root=str(tmp_path), file_nodes=file_nodes, include_external=False
    )

    inc_edges = [e for e in g.edges if e.label == "includes"]
    # Two distinct (a.cpp -> foo.h) and (b.cpp -> foo.h); no duplicates.
    assert len(inc_edges) == 2
    triples = {(e.source_id, e.label, e.target_id) for e in inc_edges}
    assert ("src/a.cpp", "includes", "src/foo.h") in triples
    assert ("src/b.cpp", "includes", "src/foo.h") in triples


def test_external_includes_skipped_by_default(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (external / "lib.h").write_text("inline int leak() { return 0; }\n")

    src = project / "src" / "main.cpp"
    src.parent.mkdir()
    src.write_text('#include "lib.h"\nint use() { return leak(); }\n')

    g = Graph("demo")
    file_nodes = emit_filesystem_hierarchy(
        g, project_name="demo", root=project, files=[str(src.resolve())]
    )
    idx = make_index()
    args = fallback_args_for_file(src, extra_include_dirs=[str(external)])
    result = parse_translation_unit(idx, filename=src, arguments=args)
    assert not result.had_fatal, result.diagnostics
    emit_include_edges(
        g, [result.tu], project_root=str(project), file_nodes=file_nodes, include_external=False
    )

    # No external File node should have been created; no edges to it.
    for n in g.nodes:
        assert "external" not in n.properties, n.id
    inc_edges = [e for e in g.edges if e.label == "includes"]
    assert inc_edges == []


def test_external_includes_emitted_when_flag_set(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (external / "lib.h").write_text("inline int leak() { return 0; }\n")

    src = project / "src" / "main.cpp"
    src.parent.mkdir()
    src.write_text('#include "lib.h"\nint use() { return leak(); }\n')

    g = Graph("demo")
    file_nodes = emit_filesystem_hierarchy(
        g, project_name="demo", root=project, files=[str(src.resolve())]
    )
    idx = make_index()
    args = fallback_args_for_file(src, extra_include_dirs=[str(external)])
    result = parse_translation_unit(idx, filename=src, arguments=args)
    emit_include_edges(
        g, [result.tu], project_root=str(project), file_nodes=file_nodes, include_external=True
    )

    # We should have at least one external File node + an includes edge to it.
    external_nodes = [n for n in g.nodes if n.properties.get("external")]
    assert any(n.properties.get("simpleName") == "lib.h" for n in external_nodes)
    inc_edges = [e for e in g.edges if e.label == "includes"]
    assert any(
        e.target_id.startswith("external:") and e.target_id.endswith("lib.h")
        for e in inc_edges
    )
