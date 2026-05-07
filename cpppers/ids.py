"""ID and qualified-name helpers.

Per section 3.3 of the recommendation:
* Symbol nodes (Type, Operation, Variable, Scope) are keyed by clang's
  USR (``cursor.get_usr()``) directly. The USR is deterministic and
  cross-TU stable; we don't munge it.
* File and Folder nodes are keyed by the path *relative to the input
  root*, with forward slashes (Windows-friendly canonical form).
"""

from __future__ import annotations

import os
from pathlib import Path


def relpath_id(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    """Path relative to ``root``, normalised to forward slashes.

    Raises ``ValueError`` if ``path`` is not under ``root`` — fail loudly
    rather than silently emitting nodes with absolute or unexpected ids.
    """
    p = Path(path).resolve()
    r = Path(root).resolve()
    rel = p.relative_to(r)  # raises ValueError if not under root
    return rel.as_posix()


def is_under(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """Non-raising counterpart to :func:`relpath_id`.

    Useful to decide ``project-internal`` vs ``external`` when walking
    cursors that may originate in vendored or system headers.
    """
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def fallback_anonymous_id(file_relpath: str, line: int, col: int) -> str:
    """Fallback id for cursors with empty ``spelling`` and no USR.

    Format mirrors §3.4 of the recommendation: ``<file>::anon@<line>:<col>``.
    """
    return f"{file_relpath}::anon@{line}:{col}"
