"""Labelled property graph primitives.

Mirrors ``csharpers/CSharPers/LPG/{Nodes,Edges,Graph}.cs``:
* ``Node`` identity = ``id`` (set semantics).
* ``Edge`` identity = ``(source, target, label)`` triple.
* ``Graph`` is just a pair of de-duplicating containers.

Extensive de-duplication is critical — a single SABO graph may be
populated from many translation units that all see the same header,
and we want one node per USR no matter how many times we encounter it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator


class Node:
    __slots__ = ("id", "labels", "properties")

    def __init__(self, id: str, *labels: str) -> None:
        if not id:
            raise ValueError("Node id must be non-empty")
        self.id: str = id
        self.labels: list[str] = list(labels)
        self.properties: dict[str, object] = {}

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Node) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"Node(id={self.id!r}, labels={self.labels!r})"


class Edge:
    __slots__ = ("source_id", "target_id", "label", "properties")

    def __init__(self, source_id: str, target_id: str, label: str) -> None:
        if not source_id or not target_id or not label:
            raise ValueError("Edge requires non-empty source, target, label")
        self.source_id: str = source_id
        self.target_id: str = target_id
        self.label: str = label
        self.properties: dict[str, object] = {"weight": 1}

    @property
    def id(self) -> str:
        return f"{self.source_id}-{self.label}-{self.target_id}"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Edge)
            and self.source_id == other.source_id
            and self.target_id == other.target_id
            and self.label == other.label
        )

    def __hash__(self) -> int:
        return hash((self.source_id, self.target_id, self.label))

    def __repr__(self) -> str:
        return f"Edge({self.source_id!r} -[{self.label}]-> {self.target_id!r})"


class _IdentitySet(set):
    """Set that returns the existing element on duplicate-add, like a cache.

    The vanilla ``set.add`` returns ``None`` whether the element was new
    or not. During extraction we frequently want to *get back* the canonical
    instance for a given identity (e.g., to mutate its ``properties``).
    """

    def add_or_get(self, item):  # type: ignore[override]
        # ``set`` doesn't expose a way to fetch the canonical stored copy
        # of an equivalent element, so we lookup by iteration only on miss.
        if item in self:
            for existing in self:
                if existing == item:
                    return existing
        self.add(item)
        return item


class Nodes(_IdentitySet):
    def find_by_id(self, id: str) -> Node | None:
        for n in self:
            if n.id == id:
                return n
        return None

    def with_label(self, label: str) -> list[Node]:
        return [n for n in self if label in n.labels]


class Edges(_IdentitySet):
    pass


@dataclass
class Graph:
    name: str
    nodes: Nodes = field(default_factory=Nodes)
    edges: Edges = field(default_factory=Edges)

    def add_node(self, node: Node) -> Node:
        return self.nodes.add_or_get(node)

    def add_edge(self, edge: Edge) -> Edge:
        return self.edges.add_or_get(edge)

    def __iter__(self) -> Iterator[Node | Edge]:
        yield from self.nodes
        yield from self.edges
