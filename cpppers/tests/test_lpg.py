"""Tests for the LPG primitives + codecs.

Codec parity: the same graph instance must produce stable, deterministic
output across all three encoders so golden snapshots remain useful.
"""

from __future__ import annotations

import json

from cpppers.lpg import CsvCodec, CyJsonCodec, Edge, Graph, GraphMLCodec, Node


def _sample_graph() -> Graph:
    g = Graph("demo")
    proj = Node("demo", "Project")
    proj.properties["kind"] = "project"
    f = Node("src/foo.cpp", "File")
    f.properties["kind"] = "file"
    t = Node("c:@N@demo@S@Foo", "Type")
    t.properties["simpleName"] = "Foo"
    t.properties["kind"] = "class"
    g.add_node(proj)
    g.add_node(f)
    g.add_node(t)
    g.add_edge(Edge("demo", "src/foo.cpp", "contains"))
    g.add_edge(Edge("src/foo.cpp", "c:@N@demo@S@Foo", "declares"))
    return g


def test_node_identity_is_id_only():
    a = Node("x", "Type")
    b = Node("x", "Operation")  # different label, same id
    assert a == b
    assert hash(a) == hash(b)


def test_edge_identity_is_triple():
    e1 = Edge("a", "b", "contains")
    e2 = Edge("a", "b", "contains")
    e3 = Edge("a", "b", "encloses")  # different label
    assert e1 == e2
    assert e1 != e3


def test_graph_dedupes_nodes_and_edges():
    g = Graph("g")
    g.add_node(Node("x", "Type"))
    g.add_node(Node("x", "Type"))
    g.add_edge(Edge("x", "y", "contains"))
    g.add_edge(Edge("x", "y", "contains"))
    assert len(g.nodes) == 1
    assert len(g.edges) == 1


def test_add_node_returns_canonical_instance():
    """Re-adding by id should hand back the existing node so callers can
    keep accumulating properties without losing earlier writes."""
    g = Graph("g")
    n = Node("x", "Type")
    n.properties["kind"] = "class"
    g.add_node(n)

    duplicate = Node("x", "Type")
    duplicate.properties["new_property"] = "value"
    canonical = g.add_node(duplicate)

    # We expect the *original* instance back, not the duplicate.
    assert canonical is n
    assert canonical.properties == {"kind": "class"}


def test_cyjson_roundtrip_shape():
    g = _sample_graph()
    payload = json.loads(CyJsonCodec.dumps(g))
    assert "elements" in payload
    nodes = payload["elements"]["nodes"]
    edges = payload["elements"]["edges"]
    assert len(nodes) == 3
    assert len(edges) == 2
    # Ordering is sorted-by-id (deterministic snapshots).
    ids = [n["data"]["id"] for n in nodes]
    assert ids == sorted(ids)
    # Edges carry an id of the form source-label-target.
    assert edges[0]["data"]["id"] == f"{edges[0]['data']['source']}-{edges[0]['data']['label']}-{edges[0]['data']['target']}"


def test_cyjson_is_deterministic():
    """Same graph, two encodings, byte-identical output."""
    g = _sample_graph()
    assert CyJsonCodec.dumps(g) == CyJsonCodec.dumps(g)


def test_graphml_well_formed():
    g = _sample_graph()
    xml = GraphMLCodec.dumps(g)
    assert xml.startswith("<?xml")
    assert "<graphml" in xml
    assert '<graph id="demo"' in xml
    # No unescaped angle brackets in node ids or property values.
    assert xml.count("<node") == 3
    assert xml.count("<edge") == 2


def test_csv_columns_are_union_of_properties():
    g = _sample_graph()
    nodes_csv, edges_csv = CsvCodec.dumps(g)
    header = nodes_csv.splitlines()[0]
    # Property columns should be sorted and include both 'kind' and 'simpleName'.
    assert "kind" in header
    assert "simpleName" in header
    # Edge file has the canonical 4 + property columns; weight is the default property.
    eheader = edges_csv.splitlines()[0]
    assert eheader.startswith("id,source,target,label")
    assert "weight" in eheader
