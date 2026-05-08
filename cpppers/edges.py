"""Semantic-edge emission — type system and call graph.

This is the second half of phase 2. Once :mod:`walker` has emitted one
``Node`` per USR (Type/Operation/Variable/Scope), this module wires the
edges that need *cross-cursor* resolution:

| edge label      | source     | target     | clang hook                           |
|-----------------|------------|------------|--------------------------------------|
| parameterizes   | Variable   | Operation  | TEMPLATE_*_PARAMETER child of FUNCTION_TEMPLATE / CLASS_TEMPLATE |
| returns         | Operation  | Type       | cursor.result_type                    |
| typed           | Variable   | Type       | cursor.type                           |
| typed           | Type       | Type       | TYPEDEF_DECL.underlying_typedef_type  |
| specializes     | Type       | Type       | get_children of CXX_BASE_SPECIFIER    |
| overrides       | Operation  | Operation  | cursor.get_overriden_cursors()        |
| invokes         | Operation  | Operation  | DescendantNodes CALL_EXPR             |
| instantiates    | Operation  | Type       | DescendantNodes CXX_NEW_EXPR / CTOR   |
| uses            | Operation  | Variable   | DescendantNodes DECL_REF_EXPR → field |

We only emit an edge when *both* endpoints have a Node in the graph
(i.e., we have their USR in ``usr_to_node``). Dangling edges to
external symbols would just bloat the graph; downstream consumers
that need a richer cross-link can run with ``--include-external``.
"""

from __future__ import annotations

from typing import Iterable

from .lpg import Edge, Graph, Node


def emit_semantic_edges(
    graph: Graph,
    translation_units: Iterable[object],
    *,
    usr_to_node: dict[str, Node],
) -> None:
    """Walk every TU again to emit type-system + call edges.

    A second walk is necessary because phase 1 only buffered ``SymbolEntry``
    structures (location, USR, kind) — it deliberately did not capture
    cross-cursor relationships, which would have required materialising a
    big chunk of the cursor tree as Python objects. Walking again lets us
    keep clang's lazy ``Cursor`` semantics intact.
    """
    from clang.cindex import CursorKind

    for tu in translation_units:
        for cursor in tu.cursor.walk_preorder():
            kind = cursor.kind
            usr = cursor.get_usr()
            if not usr or usr not in usr_to_node:
                # Either we already filtered this cursor (external symbol),
                # or it's not a SABO-relevant decl.
                continue
            node = usr_to_node[usr]

            if kind in (CursorKind.CLASS_TEMPLATE, CursorKind.FUNCTION_TEMPLATE):
                _emit_template_parameters(graph, cursor, node, usr_to_node)

            if kind in (
                CursorKind.FUNCTION_DECL,
                CursorKind.CXX_METHOD,
                CursorKind.CONSTRUCTOR,
                CursorKind.DESTRUCTOR,
                CursorKind.CONVERSION_FUNCTION,
                CursorKind.FUNCTION_TEMPLATE,
            ):
                _emit_returns(graph, cursor, node, usr_to_node)
                _emit_overrides(graph, cursor, node, usr_to_node)
                _emit_invokes_uses_instantiates(graph, cursor, node, usr_to_node)

            if kind in (
                CursorKind.FIELD_DECL,
                CursorKind.PARM_DECL,
                CursorKind.VAR_DECL,
            ):
                _emit_typed_for_variable(graph, cursor, node, usr_to_node)

            if kind in (
                CursorKind.CLASS_DECL,
                CursorKind.STRUCT_DECL,
                CursorKind.CLASS_TEMPLATE,
                CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
            ):
                _emit_base_specializes(graph, cursor, node, usr_to_node)

            if kind in (
                CursorKind.TYPEDEF_DECL,
                CursorKind.TYPE_ALIAS_DECL,
            ):
                _emit_typed_for_alias(graph, cursor, node, usr_to_node)


# ----------------------------------------------------------------------------
# Helpers — one per edge family.
# ----------------------------------------------------------------------------


def _resolve_type_to_usr(clang_type) -> str | None:  # type: ignore[no-untyped-def]
    """Resolve a clang ``Type`` to the USR of its declaration, if knowable.

    We canonicalise (``get_canonical()``) so that aliases and references
    resolve to the underlying type's declaration — that's the node we
    want to point ``typed`` / ``returns`` / ``instantiates`` at.
    """
    if clang_type is None:
        return None
    try:
        canonical = clang_type.get_canonical()
        decl = canonical.get_declaration()
    except Exception:
        return None
    if decl is None:
        return None
    usr = decl.get_usr()
    return usr or None


def _emit_template_parameters(
    graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]
) -> None:
    """``Variable -parameterizes-> Operation/Type`` for each template parameter.

    Per §3.4: ``CLASS_TEMPLATE`` / ``FUNCTION_TEMPLATE`` keep one node per
    template definition; per-parameter ``Variable`` nodes (already emitted
    by the walker) point at the template via ``parameterizes``. We do NOT
    emit a node per instantiation.
    """
    from clang.cindex import CursorKind

    template_param_kinds = {
        CursorKind.TEMPLATE_TYPE_PARAMETER,
        CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
        CursorKind.TEMPLATE_TEMPLATE_PARAMETER,
    }
    for child in cursor.get_children():
        if child.kind not in template_param_kinds:
            continue
        param_usr = child.get_usr()
        if not param_usr or param_usr not in usr_to_node:
            continue
        graph.add_edge(Edge(usr_to_node[param_usr].id, node.id, "parameterizes"))


def _emit_returns(graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]) -> None:
    """``Operation -returns-> Type`` for each non-void return type."""
    try:
        rt = cursor.result_type
    except Exception:
        return
    target_usr = _resolve_type_to_usr(rt)
    if target_usr is None or target_usr not in usr_to_node:
        return
    graph.add_edge(Edge(node.id, usr_to_node[target_usr].id, "returns"))


def _emit_overrides(graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]) -> None:
    """``Operation -overrides-> Operation`` for each parent virtual method.

    The Python libclang binding does NOT expose
    ``clang_getOverriddenCursors`` (verified empirically: ``dir(Cursor)``
    contains no ``overrid*`` method). Rather than reach into private
    ctypes internals (the bound ``CXCursor`` Structure layout is not part
    of the Python binding's public API), we reconstruct overrides
    structurally by walking the containing class's base classes and
    looking for a same-name, same-arity, virtual method.

    Trade-offs:
    * Misses overload resolution edge cases where C++ would refuse to
      consider a same-name base method as an override (e.g., differing
      const-qualification on a non-virtual base). For SABO graph
      visualisation that's an acceptable false-positive rate.
    * Catches the cases that matter: virtual-then-override across class
      hierarchies, including diamond inheritance.
    """
    from clang.cindex import CursorKind

    if not cursor.is_virtual_method() and not cursor.is_pure_virtual_method():
        # If we're not virtual ourselves we can't override anything in
        # the SABO sense — skip the (potentially expensive) base walk.
        # We still allow non-`override`-keyword overrides through because
        # some legacy code omits it; that's why we only gate on virtuality.
        if not _has_override_attr(cursor):
            return

    parent_type = cursor.semantic_parent
    if parent_type is None or parent_type.kind not in (
        CursorKind.CLASS_DECL,
        CursorKind.STRUCT_DECL,
        CursorKind.CLASS_TEMPLATE,
        CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
    ):
        return

    arity = sum(1 for c in cursor.get_children() if c.kind == CursorKind.PARM_DECL)
    name = cursor.spelling

    visited_bases: set[str] = set()
    for base_method in _walk_base_methods(parent_type, visited_bases):
        if base_method.spelling != name:
            continue
        base_arity = sum(1 for c in base_method.get_children() if c.kind == CursorKind.PARM_DECL)
        if base_arity != arity:
            continue
        if not (base_method.is_virtual_method() or base_method.is_pure_virtual_method()):
            continue
        usr = base_method.get_usr()
        if not usr or usr not in usr_to_node:
            continue
        graph.add_edge(Edge(node.id, usr_to_node[usr].id, "overrides"))


def _has_override_attr(cursor) -> bool:
    """Heuristic: does this method have ``override`` written on it?

    Used as a backstop for overrides where ``is_virtual_method()`` returns
    False (which can happen for definitions outside the class body).
    """
    from clang.cindex import CursorKind

    for child in cursor.get_children():
        if child.kind == CursorKind.CXX_OVERRIDE_ATTR:
            return True
    return False


def _walk_base_methods(class_cursor, visited: set[str]):
    """Yield every method visible in ``class_cursor``'s base hierarchy.

    Cycle-guarded by USR so diamond inheritance is fine. Walks bases
    breadth-first; emits methods in the order the bases declare them
    (deterministic for golden-snapshot tests downstream).
    """
    from clang.cindex import CursorKind

    queue = [class_cursor]
    while queue:
        cur = queue.pop(0)
        for child in cur.get_children():
            if child.kind != CursorKind.CXX_BASE_SPECIFIER:
                continue
            base_decl = child.referenced
            if base_decl is None:
                continue
            base_usr = base_decl.get_usr() or ""
            if base_usr in visited:
                continue
            visited.add(base_usr)
            for member in base_decl.get_children():
                if member.kind in (
                    CursorKind.CXX_METHOD,
                    CursorKind.DESTRUCTOR,
                    CursorKind.CONVERSION_FUNCTION,
                ):
                    yield member
            queue.append(base_decl)


def _emit_invokes_uses_instantiates(
    graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]
) -> None:
    """Walk the body of an Operation and emit invokes / uses / instantiates.

    Definition cursors contain the body; declaration cursors don't. We
    only want to walk the body once per logical method, so we restrict
    to definition cursors. Calls inside non-definition decls (impossible
    in practice) would just be skipped.
    """
    from clang.cindex import CursorKind

    if not cursor.is_definition():
        return

    for descendant in cursor.walk_preorder():
        d_kind = descendant.kind

        if d_kind == CursorKind.CALL_EXPR:
            # The referenced cursor is the called method/function.
            ref = descendant.referenced
            if ref is None:
                continue
            usr = ref.get_usr()
            if not usr or usr not in usr_to_node:
                continue
            target = usr_to_node[usr]
            # If the referenced cursor is a constructor, this is an
            # instantiation — Operation -instantiates-> Type. Otherwise
            # it's a plain invocation.
            if ref.kind == CursorKind.CONSTRUCTOR:
                ctor_parent_usr = ref.semantic_parent.get_usr() if ref.semantic_parent else None
                if ctor_parent_usr and ctor_parent_usr in usr_to_node:
                    graph.add_edge(
                        Edge(node.id, usr_to_node[ctor_parent_usr].id, "instantiates")
                    )
                continue
            graph.add_edge(Edge(node.id, target.id, "invokes"))
            continue

        if d_kind == CursorKind.CXX_NEW_EXPR:
            t_usr = _resolve_type_to_usr(getattr(descendant, "type", None))
            if t_usr and t_usr in usr_to_node:
                graph.add_edge(Edge(node.id, usr_to_node[t_usr].id, "instantiates"))
            continue

        if d_kind in (CursorKind.MEMBER_REF_EXPR, CursorKind.DECL_REF_EXPR):
            ref = descendant.referenced
            if ref is None:
                continue
            if ref.kind not in (
                CursorKind.FIELD_DECL,
                CursorKind.VAR_DECL,
                CursorKind.PARM_DECL,
                CursorKind.ENUM_CONSTANT_DECL,
            ):
                continue
            usr = ref.get_usr()
            if not usr or usr not in usr_to_node:
                continue
            graph.add_edge(Edge(node.id, usr_to_node[usr].id, "uses"))


def _emit_typed_for_variable(
    graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]
) -> None:
    """``Variable -typed-> Type`` from ``cursor.type``."""
    try:
        t = cursor.type
    except Exception:
        return
    usr = _resolve_type_to_usr(t)
    if usr and usr in usr_to_node:
        graph.add_edge(Edge(node.id, usr_to_node[usr].id, "typed"))


def _emit_typed_for_alias(
    graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]
) -> None:
    """``Type(alias) -typed-> Type`` for typedef / using declarations."""
    try:
        underlying = cursor.underlying_typedef_type
    except Exception:
        return
    usr = _resolve_type_to_usr(underlying)
    if usr and usr in usr_to_node:
        graph.add_edge(Edge(node.id, usr_to_node[usr].id, "typed"))


def _emit_base_specializes(
    graph: Graph, cursor, node: Node, usr_to_node: dict[str, Node]
) -> None:
    """``Type -specializes-> Type`` for inheritance.

    libclang exposes inheritance as ``CXX_BASE_SPECIFIER`` children of the
    derived class. We resolve each base specifier's referenced cursor to
    a USR and emit one ``specializes`` edge per base.
    """
    from clang.cindex import CursorKind

    for child in cursor.get_children():
        if child.kind != CursorKind.CXX_BASE_SPECIFIER:
            continue
        ref = child.referenced
        if ref is None:
            ref_usr = _resolve_type_to_usr(child.type)
        else:
            ref_usr = ref.get_usr() or None
        if not ref_usr or ref_usr not in usr_to_node:
            continue
        graph.add_edge(Edge(node.id, usr_to_node[ref_usr].id, "specializes"))
