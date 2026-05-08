"""Tests for type-system + call-graph edge emission.

Each test pins exactly one edge family so a regression points at a
specific helper in :mod:`cpppers.edges`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cindex = pytest.importorskip("clang.cindex")

from cpppers.cdb import fallback_args_for_file
from cpppers.edges import emit_semantic_edges
from cpppers.fs_walk import emit_filesystem_hierarchy
from cpppers.lpg import Graph
from cpppers.parsing import make_index, parse_translation_unit
from cpppers.walker import emit_symbol_nodes, walk_translation_units


def _build(tmp_path: Path, sources: dict[str, str]):
    paths = []
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
    emit_semantic_edges(g, tus, usr_to_node=usr_to_node)
    return g, usr_to_node


def _node(g, label: str, simple: str):
    return next(
        n
        for n in g.nodes
        if label in n.labels and n.properties.get("simpleName") == simple
    )


def _triples(g):
    return {(e.source_id, e.label, e.target_id) for e in g.edges}


def test_specializes_on_inheritance(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/inh.cpp": """
                class Base { public: virtual int run() { return 0; } };
                class Derived : public Base { public: int run() override { return 1; } };
            """,
        },
    )
    base = _node(g, "Type", "Base")
    derived = _node(g, "Type", "Derived")
    assert (derived.id, "specializes", base.id) in _triples(g)


def test_overrides_on_virtual_method(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/inh.cpp": """
                class Base { public: virtual int run() { return 0; } };
                class Derived : public Base { public: int run() override { return 1; } };
            """,
        },
    )
    # Pick the Operation `run` whose definedIn says it's the Derived one.
    base_run = next(
        n
        for n in g.nodes
        if "Operation" in n.labels
        and n.properties.get("simpleName") == "run"
        and "Base" in n.id
    )
    derived_run = next(
        n
        for n in g.nodes
        if "Operation" in n.labels
        and n.properties.get("simpleName") == "run"
        and "Derived" in n.id
    )
    assert (derived_run.id, "overrides", base_run.id) in _triples(g)


def test_returns_and_typed_field(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/r.cpp": """
                class Foo { public: int n; };
                class Bar { public: Foo make() { return Foo{}; } };
            """,
        },
    )
    foo = _node(g, "Type", "Foo")
    make = _node(g, "Operation", "make")
    n_field = _node(g, "Variable", "n")
    triples = _triples(g)
    assert (make.id, "returns", foo.id) in triples
    assert (n_field.id, "typed", foo.id) not in triples  # int isn't in graph
    # An int field has no graph node for its type, so no `typed` edge —
    # that's correct: dangling edges are intentionally not emitted.


def test_typed_edge_when_field_type_is_a_user_class(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/t.cpp": """
                class Inner {};
                class Outer { public: Inner i; };
            """,
        },
    )
    inner = _node(g, "Type", "Inner")
    i = _node(g, "Variable", "i")
    assert (i.id, "typed", inner.id) in _triples(g)


def test_invokes_call_edge(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/c.cpp": """
                void target() {}
                void caller() { target(); target(); }
            """,
        },
    )
    target = _node(g, "Operation", "target")
    caller = _node(g, "Operation", "caller")
    # Same edge added twice → set semantics → exactly one.
    invokes = [e for e in g.edges if e.label == "invokes"]
    assert (caller.id, "invokes", target.id) in _triples(g)
    assert len(invokes) == 1


def test_uses_field_access(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/u.cpp": """
                class Foo { public: int n; int get() { return n; } };
            """,
        },
    )
    n_field = _node(g, "Variable", "n")
    get = _node(g, "Operation", "get")
    assert (get.id, "uses", n_field.id) in _triples(g)


def test_instantiates_on_constructor_call(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/i.cpp": """
                class Foo { public: Foo() {} };
                void make() { Foo f; }
            """,
        },
    )
    foo = _node(g, "Type", "Foo")
    make = _node(g, "Operation", "make")
    assert (make.id, "instantiates", foo.id) in _triples(g)


def test_parameterizes_for_class_template(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/tmpl.cpp": """
                template <typename T, int N>
                class Buffer { public: T data[N]; };
            """,
        },
    )
    # Type node for the template definition (one node, not one per
    # instantiation — per §3.4).
    buffers = [n for n in g.nodes if "Type" in n.labels and n.properties.get("simpleName") == "Buffer"]
    assert len(buffers) == 1
    buf = buffers[0]

    triples = _triples(g)
    # Both T and N should have parameterizes edges to Buffer.
    t = _node(g, "Variable", "T")
    n = _node(g, "Variable", "N")
    assert (t.id, "parameterizes", buf.id) in triples
    assert (n.id, "parameterizes", buf.id) in triples


def test_typedef_emits_alias_type_with_typed_edge(tmp_path):
    g, _ = _build(
        tmp_path,
        {
            "src/a.cpp": """
                class Real {};
                using Alias = Real;
                typedef Real Tdef;
            """,
        },
    )
    real = _node(g, "Type", "Real")
    alias = _node(g, "Type", "Alias")
    tdef = _node(g, "Type", "Tdef")
    triples = _triples(g)
    assert alias.properties["kind"] == "alias"
    assert tdef.properties["kind"] == "alias"
    assert (alias.id, "typed", real.id) in triples
    assert (tdef.id, "typed", real.id) in triples
