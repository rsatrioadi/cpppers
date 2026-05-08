"""Walker tests: phase-1 buffering and phase-2 node emission.

We check the *node-side* of the walker only here:
* USR-keyed Type/Operation/Variable/Scope nodes.
* ``encloses`` for Scope→Type and Type→nested-Type.
* ``encapsulates`` for Type→Operation, Type→Variable.
* ``declares`` from every File touching the symbol.

Type-system and call edges are tested in their own file once batch 5
lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cindex = pytest.importorskip("clang.cindex")

from cpppers.cdb import fallback_args_for_file
from cpppers.fs_walk import emit_filesystem_hierarchy
from cpppers.lpg import Graph
from cpppers.parsing import make_index, parse_translation_unit
from cpppers.walker import emit_symbol_nodes, walk_translation_units


def _build_graph(tmp_path: Path, sources: dict[str, str]):
    """Helper: write fixture files, run libclang on each .cpp, return graph + USR map."""
    paths: list[Path] = []
    for rel, content in sources.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        paths.append(p)

    abs_files = [str(p.resolve()) for p in paths]
    g = Graph("demo")
    file_nodes = emit_filesystem_hierarchy(
        g, project_name="demo", root=tmp_path, files=abs_files
    )

    idx = make_index()
    tus = []
    for p in paths:
        if p.suffix.lower() not in (".cpp", ".cc", ".cxx", ".c"):
            continue
        args = fallback_args_for_file(p, extra_include_dirs=[str(tmp_path)])
        result = parse_translation_unit(idx, filename=p, arguments=args)
        assert not result.had_fatal, result.diagnostics
        tus.append(result.tu)

    table = walk_translation_units(
        tus,
        project_root=str(tmp_path.resolve()),
        include_external=False,
        file_paths_in_project=set(abs_files),
    )
    usr_to_node = emit_symbol_nodes(
        g, table, project_root=str(tmp_path.resolve()), file_nodes=file_nodes
    )
    return g, usr_to_node, table


def test_class_method_field_emitted_with_correct_labels(tmp_path):
    g, _, _ = _build_graph(
        tmp_path,
        {
            "src/foo.cpp": """
                namespace demo {
                    class Foo {
                    public:
                        int bar(int x);
                        int field;
                    };
                    int Foo::bar(int x) { return x + field; }
                }
            """,
        },
    )

    types = [n for n in g.nodes if "Type" in n.labels]
    ops = [n for n in g.nodes if "Operation" in n.labels]
    vars_ = [n for n in g.nodes if "Variable" in n.labels]
    scopes = [n for n in g.nodes if "Scope" in n.labels]

    type_names = {n.properties["simpleName"] for n in types}
    op_names = {n.properties["simpleName"] for n in ops}
    var_names = {n.properties["simpleName"] for n in vars_}
    scope_names = {n.properties["simpleName"] for n in scopes}

    assert "Foo" in type_names
    assert "bar" in op_names
    # field + the parameter `x` are both Variable nodes.
    assert "field" in var_names
    assert "x" in var_names
    assert "demo" in scope_names


def test_encloses_and_encapsulates_edges(tmp_path):
    g, usr_to_node, _ = _build_graph(
        tmp_path,
        {
            "src/foo.cpp": """
                namespace demo {
                    class Foo {
                    public:
                        int bar(int x);
                        int field;
                    };
                    int Foo::bar(int x) { return x + field; }
                }
            """,
        },
    )

    edge_triples = {(e.source_id, e.label, e.target_id) for e in g.edges}

    def _by(label: str, simple: str):
        return next(
            n
            for n in g.nodes
            if label in n.labels and n.properties.get("simpleName") == simple
        )

    foo = _by("Type", "Foo")
    bar = _by("Operation", "bar")
    field = _by("Variable", "field")
    demo = _by("Scope", "demo")

    # Scope demo -encloses-> Type Foo
    assert (demo.id, "encloses", foo.id) in edge_triples
    # Type Foo -encapsulates-> Operation bar
    assert (foo.id, "encapsulates", bar.id) in edge_triples
    # Type Foo -encapsulates-> Variable field
    assert (foo.id, "encapsulates", field.id) in edge_triples


def test_nested_type_uses_encloses_not_encapsulates(tmp_path):
    g, _, _ = _build_graph(
        tmp_path,
        {
            "src/nest.cpp": """
                class Outer {
                public:
                    struct Inner { int z; };
                };
            """,
        },
    )
    outer = next(n for n in g.nodes if n.properties.get("simpleName") == "Outer")
    inner = next(n for n in g.nodes if n.properties.get("simpleName") == "Inner")
    triples = {(e.source_id, e.label, e.target_id) for e in g.edges}
    assert (outer.id, "encloses", inner.id) in triples
    # And NOT encapsulates — the SABO contract for Type→Type is encloses.
    assert (outer.id, "encapsulates", inner.id) not in triples


def test_declares_edge_from_file_to_symbol(tmp_path):
    g, _, _ = _build_graph(
        tmp_path,
        {
            "src/foo.cpp": """
                class Foo { public: int bar(); };
                int Foo::bar() { return 0; }
            """,
        },
    )
    triples = {(e.source_id, e.label, e.target_id) for e in g.edges}
    foo = next(n for n in g.nodes if n.properties.get("simpleName") == "Foo")
    assert ("src/foo.cpp", "declares", foo.id) in triples


def test_header_and_cpp_observe_one_node_with_two_declares_edges(tmp_path):
    """Per §3.4: header/impl merge by USR but emit declares from BOTH files."""
    # Place the header alongside the .cpp so the relative ``#include "foo.h"``
    # works without us needing to teach the test about extra include dirs.
    g, _, _ = _build_graph(
        tmp_path,
        {
            "src/foo.h": """
                #pragma once
                namespace demo { class Foo { public: int bar(); }; }
            """,
            "src/foo.cpp": '''
                #include "foo.h"
                namespace demo { int Foo::bar() { return 0; } }
            ''',
        },
    )

    # Exactly one Operation node for `bar`.
    bar_nodes = [
        n for n in g.nodes if "Operation" in n.labels and n.properties.get("simpleName") == "bar"
    ]
    assert len(bar_nodes) == 1, [n.id for n in bar_nodes]
    bar = bar_nodes[0]

    triples = {(e.source_id, e.label, e.target_id) for e in g.edges}
    # Both files declare it.
    assert ("src/foo.h", "declares", bar.id) in triples
    assert ("src/foo.cpp", "declares", bar.id) in triples


def test_external_symbols_skipped_by_default(tmp_path):
    """Symbols from headers OUTSIDE the project root must be filtered out.

    We use a sibling directory (treated as ``-I/external``) so this test
    runs reliably without depending on the macOS SDK being discoverable
    by libclang. The discriminator is "is the cursor's file under the
    project root", which is the policy chosen in §4 q2 option (b).
    """
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (external / "lib.h").write_text("namespace lib { class External { public: int leak(); }; }\n")

    src = project / "src" / "main.cpp"
    src.parent.mkdir()
    src.write_text(
        '#include "lib.h"\n'
        "namespace app { class Internal { public: int run() { return 0; } }; }\n"
    )

    g = Graph("demo")
    file_nodes = emit_filesystem_hierarchy(
        g, project_name="demo", root=project, files=[str(src.resolve())]
    )
    idx = make_index()
    args = fallback_args_for_file(src, extra_include_dirs=[str(external)])
    result = parse_translation_unit(idx, filename=src, arguments=args)
    assert not result.had_fatal, result.diagnostics

    table = walk_translation_units(
        [result.tu],
        project_root=str(project.resolve()),
        include_external=False,
        file_paths_in_project={str(src.resolve())},
    )
    emit_symbol_nodes(g, table, project_root=str(project.resolve()), file_nodes=file_nodes)

    names = {n.properties.get("simpleName") for n in g.nodes}
    assert "Internal" in names
    assert "External" not in names
    assert "leak" not in names
    assert "lib" not in names  # the namespace from the external header
