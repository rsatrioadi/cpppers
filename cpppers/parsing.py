"""Thin wrapper around ``clang.cindex.Index.parse``.

Centralised so we can:
* Surface diagnostics in a uniform way (loud failure, quiet success).
* Set a consistent set of ``TranslationUnit.PARSE_*`` flags.
* Lazy-import ``clang.cindex`` so the rest of the package stays importable
  on machines where libclang isn't (yet) usable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass
class ParseResult:
    """The TU plus a flag indicating whether parsing produced *fatal*
    diagnostics. Non-fatal diagnostics (warnings) are kept on the TU but
    do not flip ``had_fatal``."""

    tu: object  # clang.cindex.TranslationUnit
    had_fatal: bool
    diagnostics: list[str]


def make_index():  # type: ignore[no-untyped-def]
    """Return a fresh ``clang.cindex.Index``.

    Imported lazily so test modules that don't touch libclang don't pay
    the import cost.
    """
    from clang.cindex import Index

    return Index.create()


def parse_translation_unit(
    index,  # type: ignore[no-untyped-def]
    *,
    filename: str | os.PathLike[str],
    arguments: Iterable[str],
):  # -> ParseResult
    """Parse one translation unit. Always returns ``ParseResult``.

    ``arguments`` is what the CDB / fallback layer hands us; it must
    NOT include the compiler executable or the source filename.
    """
    from clang.cindex import TranslationUnit

    options = (
        TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD  # for #include / macro fidelity
        | TranslationUnit.PARSE_INCOMPLETE  # don't reject TUs with missing headers
        | TranslationUnit.PARSE_SKIP_FUNCTION_BODIES  # we re-walk per cursor anyway
    )
    # PARSE_SKIP_FUNCTION_BODIES would defeat invokes/uses extraction —
    # turn it back off. Keeping the comment to document the trade-off.
    options &= ~TranslationUnit.PARSE_SKIP_FUNCTION_BODIES

    tu = index.parse(str(filename), args=list(arguments), options=options)
    diags = [f"{d.severity}: {d.spelling}" for d in tu.diagnostics]
    fatal = any(d.severity >= 3 for d in tu.diagnostics)  # 3 == Error, 4 == Fatal
    return ParseResult(tu=tu, had_fatal=fatal, diagnostics=diags)
