"""CSV codec — emits two files: ``<base>-nodes.csv`` and ``<base>-edges.csv``.

The dumps helper returns the pair as a ``(nodes_csv, edges_csv)`` tuple so
the format can also be tested without touching disk. Property columns are
the union of all keys seen on the corresponding kind of element.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .model import Graph


class CsvCodec:
    @staticmethod
    def _node_columns(graph: Graph) -> list[str]:
        keys: set[str] = set()
        for n in graph.nodes:
            keys.update(n.properties.keys())
        return ["id", "labels", *sorted(keys)]

    @staticmethod
    def _edge_columns(graph: Graph) -> list[str]:
        keys: set[str] = set()
        for e in graph.edges:
            keys.update(e.properties.keys())
        return ["id", "source", "target", "label", *sorted(keys)]

    @classmethod
    def dumps(cls, graph: Graph) -> tuple[str, str]:
        ncols = cls._node_columns(graph)
        ecols = cls._edge_columns(graph)

        nbuf = io.StringIO()
        nw = csv.DictWriter(nbuf, fieldnames=ncols, lineterminator="\n")
        nw.writeheader()
        for n in sorted(graph.nodes, key=lambda x: x.id):
            row = {"id": n.id, "labels": "|".join(n.labels)}
            for k in ncols[2:]:
                row[k] = n.properties.get(k, "")
            nw.writerow(row)

        ebuf = io.StringIO()
        ew = csv.DictWriter(ebuf, fieldnames=ecols, lineterminator="\n")
        ew.writeheader()
        for e in sorted(graph.edges, key=lambda x: (x.source_id, x.label, x.target_id)):
            row = {
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "label": e.label,
            }
            for k in ecols[4:]:
                row[k] = e.properties.get(k, "")
            ew.writerow(row)

        return nbuf.getvalue(), ebuf.getvalue()

    @classmethod
    def write(cls, graph: Graph, base_path: str | Path) -> None:
        nodes_csv, edges_csv = cls.dumps(graph)
        base = Path(base_path)
        base.with_name(base.name + "-nodes.csv").write_text(nodes_csv, encoding="utf-8")
        base.with_name(base.name + "-edges.csv").write_text(edges_csv, encoding="utf-8")
