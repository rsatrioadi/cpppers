"""Defaults shared by the CLI and the extractor.

The exclude list extends ``csharpers/CSharPers/Extractor/SourceOnlyCSharpGraphExtractor.cs:18-29``
with C/C++-specific build-output directories (``CMakeFiles``, ``_deps``,
``cmake-build-*``) per section 3.3 of the recommendation.
"""

from __future__ import annotations

# Directory basenames that are excluded by default — never recursed into.
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    # Cross-language build output:
    "bin",
    "obj",
    "target",
    "build",
    "dist",
    "out",
    # Vendored deps:
    "node_modules",
    "vendor",
    # VCS / IDE / OS:
    ".git",
    ".idea",
    ".vs",
    "Library",
    "Temp",
    # C/C++-specific build artefacts:
    "CMakeFiles",
    "_deps",
    "cmake-build-debug",
    "cmake-build-release",
)

# File extensions we treat as C/C++ source. Headers are always indexed
# alongside their TU; this is the "discoverable as a Translation Unit"
# set, not the full set of files we'll touch.
C_SOURCE_EXTS: tuple[str, ...] = (".c",)
CPP_SOURCE_EXTS: tuple[str, ...] = (".cpp", ".cc", ".cxx", ".c++")
C_HEADER_EXTS: tuple[str, ...] = (".h",)
CPP_HEADER_EXTS: tuple[str, ...] = (".hpp", ".hh", ".hxx", ".h++")

ALL_SOURCE_EXTS: tuple[str, ...] = C_SOURCE_EXTS + CPP_SOURCE_EXTS
ALL_HEADER_EXTS: tuple[str, ...] = C_HEADER_EXTS + CPP_HEADER_EXTS
ALL_C_CPP_EXTS: tuple[str, ...] = ALL_SOURCE_EXTS + ALL_HEADER_EXTS

# Default C++ standard when running without compile_commands.json
# (per open-question 3 in the recommendation). Section 4 recommends c++20.
DEFAULT_CXX_STD: str = "c++20"
