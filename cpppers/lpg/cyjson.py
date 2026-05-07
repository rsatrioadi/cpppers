"""Cytoscape-JSON codec.

Output shape mirrors ``csharpers/CSharPers/LPG/Codecs.cs:30-94``::

    { "elements": { "nodes": [ {"data": {...}}, ... ],
                    "edges": [ {"data": {...}}, ... ] } }

This is the format ClassViz / BubbleTeaViz consume. Stable element
ordering: nodes are sorted by id, edges by (source, label, target),
so golden snapshots stay diffable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Edge, Edges, Graph, Node, Nodes


class CyJsonCodec:
    @staticmethod
    def encode_node(node: Node) -> dict[str, Any]:
        return {
            "data": {
                "id": node.id,
                "labels": list(node.labels),
                "properties": dict(node.properties),
            }
        }

    @staticmethod
    def encode_edge(edge: Edge) -> dict[str, Any]:
        return {
            "data": {
                "id": edge.id,
                "source": edge.source_id,
                "target": edge.target_id,
                "label": edge.label,
                "properties": dict(edge.properties),
            }
        }

    @classmethod
    def encode_nodes(cls, nodes: Nodes) -> list[dict[str, Any]]:
        return [cls.encode_node(n) for n in sorted(nodes, key=lambda n: n.id)]

    @classmethod
    def encode_edges(cls, edges: Edges) -> list[dict[str, Any]]:
        return [
            cls.encode_edge(e)
            for e in sorted(edges, key=lambda e: (e.source_id, e.label, e.target_id))
        ]

    @classmethod
    def encode_graph(cls, graph: Graph) -> dict[str, Any]:
        return {
            "elements": {
                "nodes": cls.encode_nodes(graph.nodes),
                "edges": cls.encode_edges(graph.edges),
            }
        }

    @classmethod
    def dumps(cls, graph: Graph, indent: int | None = 2) -> str:
        return json.dumps(cls.encode_graph(graph), indent=indent, sort_keys=False)

    @classmethod
    def write(cls, graph: Graph, path: str | Path) -> None:
        Path(path).write_text(cls.dumps(graph), encoding="utf-8")
