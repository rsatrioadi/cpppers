"""CursorKind → SABO label / kind mapping.

Single source of truth for "what label does a clang cursor become".
Centralising it here keeps the walker dispatch readable and the
mapping easy to audit against the SABO 2.0 vocabulary.

References:
* SABO 2.0 vocabulary: §3.4 of the recommendation document
* csharpers' Roslyn → SABO mapping:
  ``csharpers/CSharPers/Extractor/SourceOnlyCSharpGraphExtractor.cs:177-184``

Note: we deliberately *do not* import ``clang.cindex`` at module top
level. Importing libclang is slow and the user may have a broken
``LIBCLANG_PATH``; we want this module to load cleanly so unit tests
that don't need libclang stay fast.
"""

from __future__ import annotations

# SABO 2.0 node labels (as enumerated in the recommendation).
NODE_LABELS = (
    "Project",
    "Folder",
    "File",
    "Scope",
    "Type",
    "Operation",
    "Variable",
    "Metric",
)

# SABO 2.0 edge labels.
EDGE_LABELS = (
    "contains",
    "includes",
    "encloses",
    "declares",
    "encapsulates",
    "parameterizes",
    "returns",
    "typed",
    "specializes",
    "overrides",
    "invokes",
    "uses",
    "instantiates",
)


def label_for_cursor(cursor) -> str | None:  # type: ignore[no-untyped-def]
    """Return the SABO node label for a clang ``Cursor``, or ``None`` to skip.

    ``None`` means: the walker should still recurse into this cursor's
    children, but emit no node for it (e.g., compound statements,
    ``unexposed`` cursors, references rather than declarations).
    """
    from clang.cindex import CursorKind  # local import: keeps unit tests fast

    try:

        k = cursor.kind

        # Namespaces / translation-unit-scope == Scope
        if k in (
            CursorKind.NAMESPACE,
            CursorKind.TRANSLATION_UNIT,
        ):
            return "Scope"

        # Aggregate types and aliases all collapse to Type. The "kind" property
        # on the resulting Node disambiguates (class / struct / union / enum / alias).
        if k in (
            CursorKind.CLASS_DECL,
            CursorKind.STRUCT_DECL,
            CursorKind.UNION_DECL,
            CursorKind.ENUM_DECL,
            CursorKind.CLASS_TEMPLATE,
            CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
            CursorKind.TYPEDEF_DECL,
            CursorKind.TYPE_ALIAS_DECL,
            CursorKind.TYPE_ALIAS_TEMPLATE_DECL,
        ):
            return "Type"

        # Functions / methods / constructors / destructors / operators == Operation
        if k in (
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.CONSTRUCTOR,
            CursorKind.DESTRUCTOR,
            CursorKind.CONVERSION_FUNCTION,
            CursorKind.FUNCTION_TEMPLATE,
        ):
            return "Operation"

        # Variables in any scope (field / param / local / global / enum-member) == Variable
        if k in (
            CursorKind.FIELD_DECL,
            CursorKind.PARM_DECL,
            CursorKind.VAR_DECL,
            CursorKind.ENUM_CONSTANT_DECL,
            CursorKind.TEMPLATE_TYPE_PARAMETER,
            CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
            CursorKind.TEMPLATE_TEMPLATE_PARAMETER,
        ):
            return "Variable"
    except:
        pass
    return None


def kind_property_for_cursor(cursor) -> str:  # type: ignore[no-untyped-def]
    """Return the ``properties.kind`` string for a Node.

    Distinguishes class vs struct vs alias etc. so downstream visualisation
    can colour appropriately. Falls back to the lower-cased CursorKind name
    so we never lose information silently.
    """
    from clang.cindex import CursorKind

    try:
        k = cursor.kind
        mapping = {
            CursorKind.NAMESPACE: "namespace",
            CursorKind.TRANSLATION_UNIT: "translation_unit",
            CursorKind.CLASS_DECL: "class",
            CursorKind.STRUCT_DECL: "struct",
            CursorKind.UNION_DECL: "union",
            CursorKind.ENUM_DECL: "enum",
            CursorKind.CLASS_TEMPLATE: "class_template",
            CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION: "partial_specialization",
            CursorKind.TYPEDEF_DECL: "alias",
            CursorKind.TYPE_ALIAS_DECL: "alias",
            CursorKind.TYPE_ALIAS_TEMPLATE_DECL: "alias",
            CursorKind.FUNCTION_DECL: "function",
            CursorKind.CXX_METHOD: "method",
            CursorKind.CONSTRUCTOR: "constructor",
            CursorKind.DESTRUCTOR: "destructor",
            CursorKind.CONVERSION_FUNCTION: "conversion",
            CursorKind.FUNCTION_TEMPLATE: "function_template",
            CursorKind.FIELD_DECL: "field",
            CursorKind.PARM_DECL: "parameter",
            CursorKind.VAR_DECL: "variable",
            CursorKind.ENUM_CONSTANT_DECL: "enum_constant",
            CursorKind.TEMPLATE_TYPE_PARAMETER: "type_parameter",
            CursorKind.TEMPLATE_NON_TYPE_PARAMETER: "non_type_parameter",
            CursorKind.TEMPLATE_TEMPLATE_PARAMETER: "template_template_parameter",
        }
        return mapping.get(k, k.name.lower())
    except:
        return ""
