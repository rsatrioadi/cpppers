"""libclang smoke test.

If libclang.dylib can't be loaded on this machine the whole test is
skipped — but everything else in the suite should still pass. This is
the canary that flags ``LIBCLANG_PATH`` issues on macOS (per §3.2 of
the recommendation) before we waste cycles on the larger end-to-end
fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cindex = pytest.importorskip("clang.cindex")

from cpppers.cdb import fallback_args_for_file
from cpppers.parsing import make_index, parse_translation_unit


def test_libclang_parses_a_trivial_cpp_file(tmp_path):
    src = tmp_path / "hello.cpp"
    src.write_text(
        """
        namespace demo {
        class Foo {
        public:
            int bar(int x);
        };
        int Foo::bar(int x) { return x + 1; }
        }
        """
    )
    idx = make_index()
    args = fallback_args_for_file(src)
    result = parse_translation_unit(idx, filename=src, arguments=args)
    assert not result.had_fatal, result.diagnostics

    # Walk the cursor tree and confirm we can see the class and the method.
    seen = set()
    for c in result.tu.cursor.walk_preorder():
        if c.location.file is None:
            continue
        if Path(str(c.location.file)).resolve() != src.resolve():
            continue
        if c.kind == cindex.CursorKind.CLASS_DECL:
            seen.add(("class", c.spelling))
        if c.kind == cindex.CursorKind.CXX_METHOD:
            seen.add(("method", c.spelling))
    assert ("class", "Foo") in seen
    assert ("method", "bar") in seen


def test_usr_is_stable_across_decl_and_definition(tmp_path):
    """``cursor.get_usr()`` is the keystone of our cross-TU dedup story.

    If a method's USR doesn't match its declaration's USR, the entire
    header/impl-merging plan in §3.4 falls apart. Belt-and-braces test.
    """
    h = tmp_path / "foo.h"
    h.write_text("namespace demo { class Foo { public: int bar(); }; }\n")
    cpp = tmp_path / "foo.cpp"
    cpp.write_text('#include "foo.h"\nnamespace demo { int Foo::bar() { return 0; } }\n')

    idx = make_index()
    args = fallback_args_for_file(cpp, extra_include_dirs=[str(tmp_path)])
    result = parse_translation_unit(idx, filename=cpp, arguments=args)
    assert not result.had_fatal, result.diagnostics

    decl_usr = None
    def_usr = None
    for c in result.tu.cursor.walk_preorder():
        if c.kind != cindex.CursorKind.CXX_METHOD or c.spelling != "bar":
            continue
        if c.is_definition():
            def_usr = c.get_usr()
        else:
            decl_usr = c.get_usr()
    assert decl_usr is not None
    assert def_usr is not None
    assert decl_usr == def_usr
