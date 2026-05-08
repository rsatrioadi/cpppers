"""``#include`` graph: ``File -includes-> File``.

Per §3.4: ``tu.get_includes()`` returns ``FileInclusion`` objects with
``source`` (the file doing the including) and ``include`` (the file
being included). We emit one ``includes`` edge per *unique* (source,
include) pair across all TUs, keeping a ``kind: "include"`` property to
distinguish it from semantic dependencies.

Includes that resolve to files outside the project root are skipped by
default (matching the external-symbols policy from §4 q2 option b).
With ``--include-external`` they're emitted with ``external: true`` on
the target File node.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .ids import is_under
from .lpg import Edge, Graph, Node


def emit_include_edges(
    graph: Graph,
    translation_units: Iterable[object],
    *,
    project_root: str,
    file_nodes: dict[str, Node],
    include_external: bool,
) -> None:
    """Emit ``File -[includes]-> File`` edges.

    ``file_nodes`` is the mapping from absolute path → File Node from
    :func:`cpppers.fs_walk.emit_filesystem_hierarchy`. We extend it on the
    fly when ``include_external`` is True so external headers also get
    a node.
    """
    project_root_resolved = str(Path(project_root).resolve())

    for tu in translation_units:
        for inclusion in tu.get_includes():
            source_file = inclusion.source
            included_file = inclusion.include
            if source_file is None or included_file is None:
                continue
            source_path = os.path.normpath(str(source_file))
            included_path = os.path.normpath(str(included_file))

            source_node = _file_node_for(
                graph,
                source_path,
                project_root=project_root_resolved,
                file_nodes=file_nodes,
                include_external=include_external,
            )
            target_node = _file_node_for(
                graph,
                included_path,
                project_root=project_root_resolved,
                file_nodes=file_nodes,
                include_external=include_external,
            )
            if source_node is None or target_node is None:
                continue

            edge = Edge(source_node.id, target_node.id, "includes")
            edge.properties["kind"] = "include"
            graph.add_edge(edge)


def _file_node_for(
    graph: Graph,
    abs_path: str,
    *,
    project_root: str,
    file_nodes: dict[str, Node],
    include_external: bool,
) -> Node | None:
    """Return (or lazily create) a File Node for ``abs_path``.

    For project-internal files we expect ``file_nodes`` to already have
    an entry (from the FS walk). For external files we create one on
    demand only when ``include_external`` is set, tagging it accordingly.
    """
    if abs_path in file_nodes:
        return file_nodes[abs_path]

    if not include_external:
        return None

    # Prefer the in-project relative path, fall back to a sentinel
    # ``external:<basename>:<hash>`` form when the file is truly outside.
    if is_under(abs_path, project_root):
        rel = Path(abs_path).resolve().relative_to(Path(project_root)).as_posix()
        node_id = rel
    else:
        # Use the absolute path as id for external files. Stable across
        # runs on the same machine; not portable across machines, but
        # neither are the system header paths themselves.
        node_id = f"external:{abs_path}"

    node = Node(node_id, "File")
    node.properties.update(
        {
            "simpleName": Path(abs_path).name,
            "qualifiedName": abs_path,
            "kind": "file",
            "external": True,
        }
    )
    canonical = graph.add_node(node)
    file_nodes[abs_path] = canonical
    return canonical
