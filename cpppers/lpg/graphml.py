"""GraphML codec — minimal XML emitter, no external dependency.

GraphML attribute keys are emitted dynamically: every property name we
encounter on any node/edge becomes a ``<key>`` declaration of type
``string`` (we round-trip values through ``str()`` to keep it simple;
downstream tools generally re-parse).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .model import Edge, Graph, Node


_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns '
    'http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">\n'
)


class GraphMLCodec:
    @staticmethod
    def _collect_keys(graph: Graph) -> tuple[set[str], set[str]]:
        node_keys: set[str] = {"labels"}
        edge_keys: set[str] = {"label"}
        for n in graph.nodes:
            node_keys.update(n.properties.keys())
        for e in graph.edges:
            edge_keys.update(e.properties.keys())
        return node_keys, edge_keys

    @classmethod
    def dumps(cls, graph: Graph) -> str:
        node_keys, edge_keys = cls._collect_keys(graph)
        out = [_HEADER]
        for k in sorted(node_keys):
            out.append(
                f'  <key id="n_{escape(k)}" for="node" attr.name="{escape(k)}" attr.type="string"/>\n'
            )
        for k in sorted(edge_keys):
            out.append(
                f'  <key id="e_{escape(k)}" for="edge" attr.name="{escape(k)}" attr.type="string"/>\n'
            )
        out.append(f'  <graph id="{escape(graph.name)}" edgedefault="directed">\n')
        for n in sorted(graph.nodes, key=lambda x: x.id):
            out.append(cls._encode_node(n))
        for e in sorted(graph.edges, key=lambda x: (x.source_id, x.label, x.target_id)):
            out.append(cls._encode_edge(e))
        out.append("  </graph>\n</graphml>\n")
        return "".join(out)

    @staticmethod
    def _encode_node(n: Node) -> str:
        parts = [f'    <node id="{escape(n.id)}">\n']
        parts.append(
            f'      <data key="n_labels">{escape(",".join(n.labels))}</data>\n'
        )
        for k, v in sorted(n.properties.items()):
            parts.append(f'      <data key="n_{escape(k)}">{escape(str(v))}</data>\n')
        parts.append("    </node>\n")
        return "".join(parts)

    @staticmethod
    def _encode_edge(e: Edge) -> str:
        parts = [
            f'    <edge id="{escape(e.id)}" '
            f'source="{escape(e.source_id)}" target="{escape(e.target_id)}">\n'
        ]
        parts.append(f'      <data key="e_label">{escape(e.label)}</data>\n')
        for k, v in sorted(e.properties.items()):
            parts.append(f'      <data key="e_{escape(k)}">{escape(str(v))}</data>\n')
        parts.append("    </edge>\n")
        return "".join(parts)

    @classmethod
    def write(cls, graph: Graph, path: str | Path) -> None:
        Path(path).write_text(cls.dumps(graph), encoding="utf-8")
