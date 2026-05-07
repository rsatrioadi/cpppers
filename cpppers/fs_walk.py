"""Filesystem-driven Project/Folder/File hierarchy.

This is phase 3 of the extraction pipeline (per §3.3 of the
recommendation). It runs *independently* of libclang, so we can test
the structural skeleton — Project, Folder, File, ``contains`` edges —
without needing a usable compile database.

The convention is to mirror ``csharpers``:
* one ``Project`` node, id = project name
* one ``Folder`` node per directory that contains discovered files
* one ``File`` node per discovered file (relative-path id)
* ``contains`` edges parent-folder → child-file
* ``contains`` edges parent-folder → child-folder
* Project ``contains`` the input root folder

Folders that don't (transitively) contain a discovered C/C++ file are
not emitted — keeps the graph proportional to actual content.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterable

from .defaults import ALL_C_CPP_EXTS, DEFAULT_EXCLUDE_DIRS
from .ids import relpath_id
from .lpg import Edge, Graph, Node


def discover_source_files(
    root: str | os.PathLike[str],
    *,
    exclude_globs: Iterable[str] = (),
    extra_exclude_dirs: Iterable[str] = (),
    extensions: Iterable[str] = ALL_C_CPP_EXTS,
) -> list[str]:
    """Return absolute paths of every C/C++ source/header below ``root``.

    Default-excluded directory basenames (e.g. ``build``, ``CMakeFiles``)
    are skipped during the walk — we don't even descend into them.
    User-supplied globs match against paths *relative* to ``root`` with
    forward slashes (so ``third_party/*`` works the same on Windows).
    """
    root_path = Path(root).resolve()
    excluded_dirs = set(DEFAULT_EXCLUDE_DIRS) | set(extra_exclude_dirs)
    user_globs = list(exclude_globs)
    exts = tuple(e.lower() for e in extensions)

    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune excluded subdirectories in place — os.walk respects this.
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        # Apply user-supplied glob excludes to subdirs too.
        if user_globs:
            kept = []
            for d in dirnames:
                rel = Path(dirpath, d).resolve().relative_to(root_path).as_posix()
                if not any(fnmatch.fnmatch(rel, g) for g in user_globs):
                    kept.append(d)
            dirnames[:] = kept

        for f in filenames:
            if not f.lower().endswith(exts):
                continue
            full = Path(dirpath, f).resolve()
            rel = full.relative_to(root_path).as_posix()
            if any(fnmatch.fnmatch(rel, g) for g in user_globs):
                continue
            results.append(str(full))
    results.sort()
    return results


def emit_filesystem_hierarchy(
    graph: Graph,
    *,
    project_name: str,
    root: str | os.PathLike[str],
    files: Iterable[str],
) -> dict[str, Node]:
    """Add Project / Folder / File nodes (and ``contains`` edges) to ``graph``.

    Returns a mapping ``{absolute_file_path -> File node}`` so subsequent
    libclang phases can wire ``declares`` / ``includes`` edges back to
    these nodes without re-walking the filesystem.
    """
    root_path = Path(root).resolve()

    # Project node (id = project name, matches csharpers convention).
    project = Node(project_name, "Project")
    project.properties.update(
        {
            "simpleName": project_name,
            "qualifiedName": str(root_path),
            "kind": "project",
        }
    )
    graph.add_node(project)

    file_nodes: dict[str, Node] = {}
    folder_nodes: dict[str, Node] = {}  # keyed by id (relpath)

    def get_or_create_folder(abs_dir: Path) -> Node:
        """Idempotent: same dir → same Node instance.

        For the project root itself we use the project name as id so the
        Project node and root Folder don't collide while still letting
        the rest of the tree be addressed by relative path.
        """
        if abs_dir == root_path:
            # Synthesise a "root folder" node distinct from Project so
            # contains edges form a clean tree (Project -[contains]-> root
            # folder -[contains]-> child folders/files).
            fid = "."
        else:
            fid = abs_dir.relative_to(root_path).as_posix()
        if fid in folder_nodes:
            return folder_nodes[fid]
        node = Node(fid, "Folder")
        node.properties.update(
            {
                "simpleName": abs_dir.name if abs_dir != root_path else project_name,
                "qualifiedName": str(abs_dir),
                "kind": "folder",
            }
        )
        graph.add_node(node)
        folder_nodes[fid] = node
        # Wire parent-folder containment, recursing up to the root.
        if abs_dir != root_path:
            parent = get_or_create_folder(abs_dir.parent)
            graph.add_edge(Edge(parent.id, node.id, "contains"))
        else:
            graph.add_edge(Edge(project.id, node.id, "contains"))
        return node

    for f in files:
        abs_f = Path(f).resolve()
        try:
            rel = abs_f.relative_to(root_path).as_posix()
        except ValueError:
            # File lives outside the input root — skip; the libclang phase
            # will decide whether to emit it as external content.
            continue

        file_node = Node(rel, "File")
        file_node.properties.update(
            {
                "simpleName": abs_f.name,
                "qualifiedName": str(abs_f),
                "kind": "file",
            }
        )
        graph.add_node(file_node)
        file_nodes[str(abs_f)] = file_node

        parent_folder = get_or_create_folder(abs_f.parent)
        graph.add_edge(Edge(parent_folder.id, file_node.id, "contains"))

    return file_nodes


__all__ = ["discover_source_files", "emit_filesystem_hierarchy"]
