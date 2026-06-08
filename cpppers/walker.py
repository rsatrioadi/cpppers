"""Cursor-kind dispatch and SABO node/edge emission.

This module implements the per-TU walk (phase 1) and the cross-TU
emission (phase 2) described in §3.3 of the recommendation.

Key design choices:

* The walker buffers a ``SymbolEntry`` for every interesting cursor and
  defers node/edge creation to a single pass over the buffered table.
  That gives us correct deduplication when the same header is included
  by N translation units — we see N copies of every cursor, but emit
  one node per USR.

* IDs come from ``cursor.get_usr()`` whenever it returns a non-empty
  string (which clang guarantees for nameable declarations, including
  anonymous ones, where it encodes the location). Empty USRs fall back
  to the synthesised ``<file-relpath>::anon@<line>:<col>`` form per §3.4.

* "External" symbols (those whose ``cursor.location.file`` lives in a
  system include path) are dropped by default and tagged ``external=true``
  when ``--include-external`` is set, per §4 question 2 option (b).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .ids import is_under
from .lpg import Edge, Graph, Node
from .vocabulary import kind_property_for_cursor, label_for_cursor
from .halstead import gather_operators_and_operands


# ----------------------------------------------------------------------------
# Phase 1 — per-TU buffering
# ----------------------------------------------------------------------------


@dataclass
class SymbolEntry:
    """One observation of a clang ``Cursor``.

    The same USR may be observed many times (header included by N TUs);
    phase-2 emission collapses to one node by USR. We keep ``is_definition``
    so we can prefer the definition's location/spelling when merging.
    """

    usr: str
    sabo_label: str
    kind: str  # properties.kind value (e.g. "class", "method")
    simple_name: str
    qualified_name: str
    file_path: str | None  # absolute path; ``None`` for built-ins
    line: int
    col: int
    is_definition: bool
    parent_usr: str | None  # nearest enclosing semantic parent's USR
    parent_label: str | None
    external: bool
    macro_synthesized: bool
    halstead_tokens: object | None = None


def _walk_one_translation_unit(
    tu,  # clang.cindex.TranslationUnit
    *,
    project_root: str,
    include_external: bool,
    file_paths_in_project: set[str],
) -> list[SymbolEntry]:
    """Phase 1: emit one ``SymbolEntry`` per interesting cursor in this TU."""
    from clang.cindex import CursorKind, TokenKind  # noqa: F401

    entries: list[SymbolEntry] = []

    def _classify(cursor) -> bool:
        """Should we keep emitting nodes for descendants of this cursor?

        We always recurse — even into ``unexposed`` cursors — because the
        labelled cursors we care about can hide arbitrarily deep inside.
        Returning True/False here only governs whether *this* cursor is
        emitted as a SymbolEntry.
        """
        return label_for_cursor(cursor) is not None

    def _is_external(file_path: str | None) -> bool:
        if file_path is None:
            return True
        return not is_under(file_path, project_root)

    def _macro_synthesized(cursor) -> bool:
        """Heuristic: a cursor whose location is inside a macro expansion.

        ``cursor.location.is_in_system_header`` is False for user macros
        but ``cursor.location.from_macro_expansion`` (when available) is
        not exposed in the python binding. We approximate by checking the
        extent: if the cursor's spelling doesn't appear at its location
        (because the location resolves to a macro definition site), it's
        almost certainly macro-synthesized. Cheap and good enough for
        the §4 q4 tagging.
        """
        try:
            ext = cursor.extent
        except Exception:
            return False
        # When clang reports an extent of zero size, the cursor was
        # synthesized by macro expansion (no source range to point at).
        return ext.start == ext.end and bool(cursor.spelling)

    def _resolve_parent_usr(cursor) -> tuple[str | None, str | None]:
        """Walk semantic parents up until we find one with a SABO label.

        We return both the USR and the SABO label so the phase-2 emitter
        can wire ``encloses`` / ``encapsulates`` / ``declares`` correctly
        without re-classifying the parent.
        """
        p = cursor.semantic_parent
        while p is not None:
            label = label_for_cursor(p)
            if label is not None and p.kind != CursorKind.TRANSLATION_UNIT:
                usr = p.get_usr()
                if usr:
                    return usr, label
            p = p.semantic_parent
        return None, None

    for cursor in tu.cursor.walk_preorder():
        if not _classify(cursor):
            continue

        loc = cursor.location
        file_path: str | None = None
        if loc.file is not None:
            file_path = os.path.normpath(str(loc.file))
        external = _is_external(file_path)
        if external and not include_external:
            continue

        usr = cursor.get_usr() or ""
        if not usr:
            # Anonymous-without-USR fallback per §3.4. We compose a stable
            # id from the file's project-relative path plus its location.
            if file_path is None:
                continue
            try:
                rel = Path(file_path).resolve().relative_to(Path(project_root).resolve()).as_posix()
            except ValueError:
                if not include_external:
                    continue
                rel = Path(file_path).name
            usr = f"{rel}::anon@{loc.line}:{loc.column}"

        label = label_for_cursor(cursor)
        if label is None:
            continue

        parent_usr, parent_label = _resolve_parent_usr(cursor)

        # Spelling for anonymous entities is empty; surface a hint so the
        # property dictionary stays informative downstream.
        simple_name = cursor.spelling or f"<anon@{loc.line}:{loc.column}>"
        try:
            qualified_name = cursor.displayname or simple_name
        except Exception:
            qualified_name = simple_name

        entries.append(
            SymbolEntry(
                usr=usr,
                sabo_label=label,
                kind=kind_property_for_cursor(cursor),
                simple_name=simple_name,
                qualified_name=qualified_name,
                file_path=file_path,
                line=loc.line,
                col=loc.column,
                is_definition=cursor.is_definition(),
                parent_usr=parent_usr,
                parent_label=parent_label,
                external=external,
                macro_synthesized=_macro_synthesized(cursor),
                halstead_tokens=gather_operators_and_operands(cursor) if label in ("Operation", "Variable") and cursor.is_definition() else None,
            )
        )

    return entries


# ----------------------------------------------------------------------------
# Phase 2 — cross-TU emission
# ----------------------------------------------------------------------------


@dataclass
class SymbolTable:
    """Collected ``SymbolEntry`` observations, keyed by USR.

    Phase 2 chooses one canonical entry per USR (definition wins, then
    first-seen) and emits a single Node. The list of *all* observations
    is retained so we can emit a ``declares`` edge from every file that
    has its hands on this symbol — header AND .cpp, per §3.4.
    """

    by_usr: dict[str, list[SymbolEntry]] = field(default_factory=dict)

    def add(self, entry: SymbolEntry) -> None:
        self.by_usr.setdefault(entry.usr, []).append(entry)

    def canonical(self, usr: str) -> SymbolEntry:
        observations = self.by_usr[usr]
        for obs in observations:
            if obs.is_definition:
                return obs
        return observations[0]


def emit_symbol_nodes(
    graph: Graph,
    table: SymbolTable,
    *,
    project_root: str,
    file_nodes: dict[str, Node],
) -> dict[str, Node]:
    """Phase 2 (node side): emit one Node per USR + ``declares``/``encloses``/``encapsulates`` edges.

    ``file_nodes`` is the mapping returned by ``emit_filesystem_hierarchy``
    (absolute file path → File Node). The walker uses it to wire ``declares``
    edges from File → symbol.

    Returns a USR → Node map so callers (subsequent edge passes) can wire
    semantic edges without re-querying the symbol table.
    """
    usr_to_node: dict[str, Node] = {}

    # First pass: create nodes (no edges yet, so parents already exist
    # before we wire encloses/encapsulates).
    for usr, observations in table.by_usr.items():
        canonical = _pick_canonical(observations)
        node = Node(usr, canonical.sabo_label)
        node.properties.update(
            {
                "simpleName": canonical.simple_name,
                "qualifiedName": canonical.qualified_name,
                "kind": canonical.kind,
            }
        )
        if canonical.external:
            node.properties["external"] = True
        if canonical.macro_synthesized:
            node.properties["macro_synthesized"] = True
        # Attach a line/col hint for the location so downstream tools can
        # jump-to-definition without re-running clang.
        if canonical.file_path is not None:
            try:
                rel = Path(canonical.file_path).resolve().relative_to(Path(project_root).resolve()).as_posix()
                node.properties["definedIn"] = rel
            except ValueError:
                node.properties["definedIn"] = canonical.file_path
            node.properties["line"] = canonical.line
            node.properties["column"] = canonical.col
        graph.add_node(node)
        usr_to_node[usr] = node

    # Second pass: parent containment (encloses / encapsulates) + declares.
    for usr, observations in table.by_usr.items():
        canonical = _pick_canonical(observations)
        node = usr_to_node[usr]

        # encloses / encapsulates: pick the relationship by parent label.
        # Per SABO 2.0:
        #   * Scope -encloses-> Scope|Type
        #   * Type  -encapsulates-> Operation|Variable
        #   * Type  -encloses-> Type   (nested classes)
        if canonical.parent_usr is not None and canonical.parent_usr in usr_to_node:
            parent_node = usr_to_node[canonical.parent_usr]
            edge_label = _parent_edge_label(canonical.parent_label, canonical.sabo_label)
            if edge_label is not None:
                graph.add_edge(Edge(parent_node.id, node.id, edge_label))

        # declares: every File that observed this symbol -> the symbol's node.
        seen_files: set[str] = set()
        for obs in observations:
            if obs.file_path is None:
                continue
            if obs.file_path in seen_files:
                continue
            seen_files.add(obs.file_path)
            file_node = file_nodes.get(obs.file_path)
            if file_node is None:
                continue
            graph.add_edge(Edge(file_node.id, node.id, "declares"))

    return usr_to_node


def _pick_canonical(observations: list[SymbolEntry]) -> SymbolEntry:
    for o in observations:
        if o.is_definition:
            return o
    return observations[0]


def _parent_edge_label(parent_label: str | None, child_label: str) -> str | None:
    """Translate a SABO parent/child pair to the appropriate containment edge.

    Returns ``None`` for combinations we deliberately don't model
    (e.g., a function nested inside another function — clang exposes
    the static-local-function pattern but it's not part of SABO).
    """
    if parent_label == "Scope":
        if child_label in ("Scope", "Type", "Operation", "Variable"):
            return "encloses"
    if parent_label == "Type":
        if child_label == "Type":
            return "encloses"  # nested class/struct
        if child_label in ("Operation", "Variable"):
            return "encapsulates"
    if parent_label == "Operation":
        # Locals / parameters of a method are bound to the method via
        # encapsulates; parameterizes (the dedicated edge for template
        # parameters) is wired separately in the type-system pass.
        if child_label == "Variable":
            return "encapsulates"
    return None


# ----------------------------------------------------------------------------
# Public entry point — the only function callers need.
# ----------------------------------------------------------------------------


def walk_translation_units(
    translation_units: Iterable[object],
    *,
    project_root: str,
    include_external: bool,
    file_paths_in_project: set[str],
) -> SymbolTable:
    """Phase-1 driver. Returns a populated :class:`SymbolTable`."""
    table = SymbolTable()
    for tu in translation_units:
        for entry in _walk_one_translation_unit(
            tu,
            project_root=project_root,
            include_external=include_external,
            file_paths_in_project=file_paths_in_project,
        ):
            table.add(entry)
    return table
