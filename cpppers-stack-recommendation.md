# cpppers — Stack recommendation for the SABO 2.0 C/C++ extractor

This document evaluates parsing-stack options for a new C/C++ source-code
extractor (`cpppers`) that conforms to SABO 2.0 conventions, following
the patterns established by `javapers`, `csharpers`, `gophers`, and
`jspers`.

This is the recommendation pass. The next pass implements.

---

## 1. Analysis of the WIP pipeline

The status-quo "Rascal WIP C/C++ extractor" is actually a two-stage
pipeline:

```
C/C++ sources  ──►  [Alpha]            ──►  M3 JSON  ──►  [M3GraphBuilder]   ──►  SABO 1.0 LPG JSON
                    Rascal + CLAIR                        Python
```

Both repos are MIT-licensed. Each has serious problems.

### 1a. Alpha (`alpha-rascal/` + `Cmake-parser-rascal/`)

**Layout.** Two Maven/Rascal subprojects: `alpha-rascal/` consumes CLAIR
to produce M3 JSON; `Cmake-parser-rascal/` parses `CMakeLists.txt` to
extract include paths and source lists.

**Dependencies.** `alpha-rascal/pom.xml:31-37` pulls in
`org.rascalmpl:rascal:0.34.2` and `org.rascalmpl:clair:0.13.1`
(latest CLAIR is 0.13.3, December 17, 2025; latest Rascal is 0.42.2,
April 14, 2026 — Alpha is several minor versions behind on both).
`META-INF/RASCAL.MF:4` declares `Require-Libraries: |lib://clair|`.

**Entry point.** `alpha-rascal/src/main/rascal/Parser.rsc:37` —
`void main(str moduleName = "")`. Invoked from a Rascal REPL
(`rascal-shell-stable.jar` → `import Parser; main(...)`); not a
self-contained CLI. User feeds it three text files:
- `cpp-files.txt` — absolute source paths (`Parser.rsc:94`)
- `include-dirs.txt` — include paths (`Parser.rsc:58`)
- `std-libs.txt` — standard-library paths (`Parser.rsc:59`)

**No `compile_commands.json` integration anywhere.** Build context comes
from Alpha's own CMake-parser, not from the standard format every
modern C++ tool consumes.

**CLAIR usage.** `Parser.rsc:185` calls
`createM3AndAstFromCppFile(filePath, stdLib=…, includeDirs=…)`. CLAIR
returns a complete Rascal M3 model; Alpha doesn't request individual
facets. CLAIR (BSD-2) wraps **Eclipse CDT** for parsing and name
resolution (confirmed at https://github.com/usethesource/clair).

**Output.** Per-translation-unit M3 JSONs in `models/<className>.json`
plus a composed system-wide JSON at `models/composed/<appName>.json`
(`Persistence.rsc:70-92`). Locations follow Rascal's M3 URI scheme
(`cpp+class:///foo::Bar`, etc.) — a format not emitted by any other
SABO extractor and downstream-coupled to M3GraphBuilder.

**Code-quality issues.**
- Hardcoded container mount: `PathMapper.rsc:8` — `str rootMount = "/app/host";`
- Hardcoded Windows project root: `Cmake-parser-rascal/PathExtractor.rsc:34` —
  `public loc ROOT = |file:///C:/Development/TF/Velox|;`
- Hardcoded output path: `Cmake-parser-rascal/Utils.rsc:135` —
  `|file:///C:/workspace/rascal/erosion-checker/output|`
- Project-specific dispatch on directory names (`/poscore/`, `/poscorered/`,
  `/poscpt/`): `PathExtractor.rsc:105-137`
- Vendor-specific CMake hacks (VxWorks, Philips 3rdParty):
  `PathExtractor.rsc:562-568`
- Hardcoded `isTest = "ON"` because the parser cannot evaluate CMake
  conditionals: `PathExtractor.rsc:275`
- Dead code: `PathExtractor.rsc:37-43` (`automatedExract()` never called)

**Rascal lock-in.** Heavy. The pipeline relies on Rascal's `loc` type,
M3 ADT (`Types.rsc:7` — `ModelContainer = tuple[M3, Declaration]`),
relation operators (composition, range restriction), and `visit`
syntax. Roughly 50–60% of the code would need rewriting; only the
CMake-parsing logic is straightforward to port.

**No test fixtures.** Input file lists point at non-existent Windows
paths.

### 1b. M3GraphBuilder (Python)

**Layout.** Pure Python, ~3,700 LOC, MIT-licensed. Consumes M3 JSON,
emits LPG JSON for ClassViz/BubbleTeaViz, plus a CSV/hierarchy export
for ARViSAN.

**Entry point.** `cli.py:6-93` — `python -m M3GraphBuilder
create-graph -m <m3_model.json> [-n NAME] [-o OUTPUT] [-v]`.
Flags don't match the SABO convention (no `--exclude`, no
`--include-external`, no `--format`).

**Vocabulary it emits** (SABO 1.0):
- Node labels: `Container` (namespaces), `Structure` (classes,
  templates, macros, translation units), `Operation` (functions,
  methods)
- Edge labels: `contains`, `hasScript`, `contains-definition`,
  `specializes`, `invokes`

**SABO 2.0 coverage matrix:**

| SABO 2.0 label | M3GraphBuilder emits? | Notes |
|---|---|---|
| `Project` | ❌ | No project-root node |
| `Folder` | ❌ | No folder hierarchy |
| `File` | ⚠️ | Only as `translation_unit` under `Structure` |
| `Scope` | ⚠️ | Namespaces emitted as `Container`, not `Scope`; translation-unit scope conflated with File |
| `Type` | ⚠️ | Emitted as `Structure` |
| `Operation` | ✅ | Label matches |
| `Variable` | ❌ | Not emitted (fields, params, locals all missing) |
| `Metric` | ❌ | No Halstead or similar |
| `contains` | ✅ | |
| `includes` | ❌ | No `#include` edges |
| `encloses` | ❌ | Not emitted |
| `declares` | ❌ | Closest is `hasScript`, semantics differ |
| `encapsulates` | ❌ | Not emitted |
| `parameterizes` | ❌ | Templates emit per-instantiation Type nodes instead |
| `returns` | ❌ | Not emitted |
| `typed` | ❌ | Not emitted |
| `specializes` | ✅ | Used for inheritance |
| `overrides` | ❌ | Not emitted |
| `invokes` | ✅ | |
| `uses` | ❌ | Not emitted |
| `instantiates` | ❌ | Not emitted |

In short: of 21 SABO 2.0 labels, the WIP emits 4 directly (`Operation`,
`contains`, `specializes`, `invokes`), partially supports 4 more, and
**misses 13**, including the entire `Variable` axis, the `Metric`
axis, and most type-system edges. This is significantly worse than
`gophers` (all node labels covered, missing only some type-system edges)
and far worse than `javapers`/`csharpers` (full coverage).

**Code-quality issues:**
- Bare `except:` swallowing all exceptions during edge recovery,
  logged at `info` level instead of `error`: `converters/cpp.py:84-108`
- Unbounded list access: `converters/cpp.py:473` — `.get("fullLocs")[0]`
  with no bounds check
- Debug `print()` left in production code: `converters/cpp.py:674`
- Fragile validator logic: `graphlib/validator.py:28` —
  `missing_ids.remove(missing_ids[0])` with unclear intent
- Placeholder implementation: `workflows.py:102-124` — `merge_graphs()`
  is a stub
- No error handling for missing M3 sections: `workflows.py:40-43`
- Hardcoded STL path: `m3_utils.py:585` —
  `cpp+classTemplate:///std/__cxx11/basic_string`
- Bare `except:` in C path: `converters/c.py:50`

**No test fixtures.** No `.cpp`/`.h` samples, no example M3 JSON, no
unit or integration tests.

### 1c. C/C++-specific gotcha handling (pipeline-level)

| Gotcha | Status | Evidence |
|---|---|---|
| Header/implementation merging | Partial | `m3_utils.py:7,37` try to associate definitions with declarations but produce separate Type nodes when source files differ |
| `#include` graph | Not handled | No parsing of `m3["includes"]`; no include edges emitted |
| Templates → one node + parameterizes | Partial | Separate nodes per `template`, `template_type`, `specialization`, `partial_specialization` (`cpp.py:366-465`); no parameterization edges; no instantiation linkage |
| Forward declarations canonicalized | Not handled | No deduplication |
| Anonymous namespaces / structs | Fragile | `m3_utils.py:467-470` labels them `"UnnamedNamespace"` (collision risk if more than one exists per scope) |
| `typedef` / `using` aliases | Not handled | No alias nodes, no `typed` edges |
| `compile_commands.json` | Not handled | Alpha consumes CMake directly via its own parser; M3GraphBuilder is downstream of M3 |

### 1d. Verdict on the WIP

The pipeline is **architecturally over-built**: three distinct components
(CMake-parser-rascal → alpha-rascal → M3GraphBuilder), each in a
different language, communicating via custom serialization formats,
to produce a graph that misses 13 of 21 SABO 2.0 labels. The Rascal
half pulls in a metaprogramming runtime to wrap a Java parser
(CLAIR/CDT) that could be called directly. The Python half exists
because Rascal isn't a comfortable graph-emission environment.

The actual SABO-emitting code (`M3GraphBuilder/converters/cpp.py`,
~720 LOC) and the graph model (`graphlib/graph.py`, ~450 LOC) are the
only artifacts worth carrying forward, and even those need substantial
rework to hit SABO 2.0.

---

## 2. Candidate stacks

| # | Candidate | License | Host language | Last upstream activity | Resolution w/o `cdb` | Resolution w/ `cdb` | Header-impl merge | Templates | Cross-platform (Linux/macOS) | SLOC est. (new extractor) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Rascal + CLAIR | BSD-2 / BSD-2 | Rascal + Java | CLAIR 0.13.3 (Dec 17 2025); Rascal 0.42.2 (Apr 14 2026) | CDT heuristics; many `__unresolved__` | Full via CDT IIndex | Yes (IIndex) | M3 DAG; collapse to def + params requires custom traversal | Pure JVM | 3.5–4.5k Rascal |
| 2 | Eclipse CDT direct | EPL-2.0 | Java/Kotlin | CDT 12.4.0 (Mar 11 2026) | Syntactic AST; `__unresolved__` bindings | `IIndex.findDeclarations()`; `getCanonicalType()` | Automatic (IIndex) | `ICPPASTTemplateDeclaration` + `ICPPASTTemplateId`; walk specializations | Pure JVM | 5–6k Kotlin |
| 3 | libclang via Python (`clang.cindex`) | Apache-2.0 + LLVM exception | Python 3 | LLVM 22.1.5 (May 5 2026); `libclang` PyPI wheel tracks LLVM | Built-ins only; cross-TU refs fail | `CompilationDatabase` → full args; `cursor.get_definition()` canonicalizes | Yes (`get_definition()` is cross-file) | `CursorKind.CLASS_TEMPLATE` etc.; manual recursion via `get_template_argument*` | Pip wheels for Linux/macOS; `LIBCLANG_PATH` env var on macOS if multiple LLVM installs | **2.5–3.5k Python** |
| 4 | libclang via C++ LibTooling | Apache-2.0 + LLVM exception | C++17 | LLVM 22.1.5 (May 5 2026) | Falls back to `-std=c++11`, scope-only | `CompilationDatabase::loadFromDirectory()`; `getCanonicalDecl()` | Automatic (`getCanonicalDecl()` across TUs) | `RecursiveASTVisitor::VisitClassTemplateDecl`; `getTemplateInstantiationPattern()` | Needs LLVM dev headers; macOS rpath quirks if Xcode/brew LLVM mixed | 4–5.5k C++ |
| 5 | tree-sitter-c / -cpp | MIT | Rust core; bindings in Py/Node/Wasm/etc. | tree-sitter-c 0.24.2 (Apr 22 2026); tree-sitter-cpp 0.23.4 (Nov 2025) | None (purely syntactic) | None (ignores build flags) | No | Syntactic only; cannot link decl ↔ definition | Excellent | 2–3k (but cannot emit `typed`, `specializes`, `overrides`, `invokes` to resolved targets, `instantiates`) |
| 6 | srcML + srcType | **GPL-3.0** (srcML) | C++ | srcML 1.1.0 (Aug 14 2025); srcType: no releases ever, last commit Apr 2024 | Undocumented; likely poor | Undocumented | Not documented | Not documented | srcML packaged for Win/Linux/macOS; srcType manual build | n/a — disqualified |
| 7 | clangd over LSP | Apache-2.0 | C++ | clangd 22.1.1 (Mar 12 2026); weekly snapshots | Poor (defaults to `clang file.cc` with no flags) | Excellent — full LSP indexing including templates, ADL, overrides | Yes (unified symbol index) | Full | Linux/macOS/Win binaries shipped | 8–12k (LSP client + symbol-index parser + SABO mapper) |
| 8 | Joern's c2cpg | Apache-2.0 | Scala (JVM 21+) | Joern 4.0.534 (May 6 2026); weekly | Limited (CDT without context) | Good (CDT + cdb); CPG includes `INHERITS_FROM`, `INSTANTIATES`, `CALL` | Yes (CDT canonicalization) | Yes (`INSTANTIATES` edges, `TYPE_PARAMETER` nodes) | Pure JVM | 4–6k Scala (CPG → SABO mapper only; c2cpg itself is reused) |

### 2.1 Per-candidate notes

**(1) Rascal + CLAIR — status quo.** Continuing means accepting the
Rascal runtime as a hard dependency and the M3 model as a forced
intermediate representation. Eclipse CDT does the actual work; everything
above it is indirection. The Rascal lock-in observed in `Parser.rsc` and
`Persistence.rsc` (relations, `visit`, `loc`-type plumbing) is
intrinsic, not avoidable. The `compile_commands.json` gap is structural:
Alpha bypasses it in favor of a custom CMake parser that already
contains vendor-specific hardcoded paths.

**(2) Eclipse CDT directly (Kotlin or Java).** Cuts out CLAIR and
Rascal; gives direct access to `IIndex`, the same name-resolution layer
CLAIR wraps. Matches `javapers`'s ecosystem (JVM + Kotlin). Verbose Java
API surface, but stable since the early 2010s. Has a JSON
compilation-database adapter (`org.eclipse.cdt.jsoncdb`) for
`compile_commands.json`. SLOC estimate is on the higher end because
CDT's API is Java-bean-heavy (lots of `IASTName`, `IBinding`,
`ICPPASTTemplateDeclaration` traversal boilerplate).

```java
IIndex index = CCorePlugin.getIndexManager().getIndex(project);
IASTTranslationUnit ast = tu.getAST(index, ITranslationUnit.AST_SKIP_INDEXED_HEADERS);
ast.accept(new ASTVisitor() {
  @Override public int visit(IASTDeclaration d) { /* emit SABO */ return PROCESS_CONTINUE; }
});
```

**(3) libclang via Python (`clang.cindex`).** The same backend as
LibTooling, accessed through Python. The `Cursor` API maps almost
1:1 to SABO node kinds. **`cursor.get_usr()` provides deterministic,
hash-free Unified Symbol Resolution strings** — exactly the
"deterministic qualified name → node ID" property the SABO conventions
require. `cursor.get_definition()` canonicalizes forward declarations
and merges header/impl pairs into one symbol. `tu.get_includes()` walks
the include graph. `clang.cindex.CompilationDatabase.fromDirectory()`
loads `compile_commands.json`. Cross-platform via the
`libclang` PyPI wheel (bundles libclang for Linux x86_64/arm64 and
macOS x86_64/arm64); on macOS with multiple LLVM installs, set
`LIBCLANG_PATH`.

```python
from clang.cindex import Index, CompilationDatabase, CursorKind
cdb = CompilationDatabase.fromDirectory(build_dir)
index = Index.create()
for cmd in cdb.getAllCompileCommands():
    tu = index.parse(cmd.filename, args=list(cmd.arguments)[1:])
    for cursor in tu.cursor.walk_preorder():
        if cursor.kind == CursorKind.CLASS_TEMPLATE:
            emit_type(cursor, kind="class", template_params=...)
```

**(4) libclang via C++ LibTooling.** Strongest fidelity (PPCallbacks
for include-graph at the preprocessor level, full RecursiveASTVisitor
hooks). Distributable as a single binary. Cost: C++ build complexity
(CMake, finding LLVM headers/libs, macOS rpath if Xcode and Homebrew
LLVM coexist). The same SABO logic in C++ runs roughly 1.5–2× the
LOC of the Python equivalent because every cursor type needs explicit
typed visitor methods.

**(5) tree-sitter-c / -cpp.** Excellent for syntax-driven tooling, but
**fundamentally incapable** of emitting `typed`, `specializes` (to a
resolved base), `overrides`, `invokes` (to a resolved target),
`instantiates`, or `uses`. It cannot canonicalize forward declarations
or merge header/impl pairs. For SABO it can emit `Project`, `Folder`,
`File`, `contains`, `includes`, and a structural skeleton — about a
third of the vocabulary. Useful as a *fallback* when no
`compile_commands.json` is available, not as a primary stack.

**(6) srcML + srcType.** **Disqualified.** srcML is GPL-3.0, which
violates the permissive-license requirement. srcType has no releases
ever, last commit April 2024, and no documented support for the
gotchas we care about. It's a stale research prototype.

**(7) clangd over LSP.** Same backend as libclang behind a language
server. Strong semantics, weekly releases, CDB-driven. The architecture
mirrors `gophers`'s use of `gopls`. But for C/C++, the canonical
"compiler-as-API" is libclang itself; talking to clangd over LSP
introduces a process-boundary/IPC layer that buys nothing libclang
doesn't already give you, and forces you to parse LSP `SymbolInformation`
back into something resembling a Cursor tree. There is also
`clangd-indexer` for batch index emission, but the resulting `.dex`
format is internal and not a stable public API.

**(8) Joern's c2cpg.** Reuses `c2cpg` (Scala, runs on JVM 21+) as the
extractor and writes only a CPG → SABO mapper. Joern's CPG schema is
mature and weekly-released; under the hood it uses Eclipse CDT, so
resolution quality matches options (1) and (2). The mapping is mostly
table-driven: CPG `NAMESPACE_BLOCK` → SABO `Scope`, `TYPE_DECL` →
`Type`, `METHOD` → `Operation`, `MEMBER`/`PARAMETER`/`LOCAL` →
`Variable`, `INHERITS_FROM` → `specializes`, `CALL` → `invokes`,
`INSTANTIATES` → `instantiates`. CPG v1.1 lacks first-class
`#include` edges; you'd have to recover them from `FILE` node metadata
or post-process. Cost: heavyweight dependency, JVM memory footprint,
locked to Joern's CPG schema evolution, Scala matches nothing in the
existing extractor stack.

---

## 3. Recommendation

**Use libclang via Python (`clang.cindex`) — option (3).**

### 3.1 Why this beats the other seven

- **vs (1) Rascal + CLAIR:** removes Rascal as a runtime dependency
  and the M3 model as a forced intermediate. Same CDT-equivalent
  resolution quality (libclang and CDT are independent implementations
  but both production-grade). No serialization-format invention.
- **vs (2) Eclipse CDT direct:** smaller (2.5–3.5k vs 5–6k SLOC),
  far cleaner dev loop (`pip install libclang` vs Maven + CDT
  bundles), deterministic IDs come for free via USR. CDT's IIndex API
  is more verbose without delivering more semantics.
- **vs (4) libclang LibTooling:** same backend, ~half the SLOC,
  trivial build. We pay the C++ LibTooling tax only for include-graph
  fidelity (PPCallbacks vs `tu.get_includes()`), and `tu.get_includes()`
  is sufficient for the basic file→file edge SABO needs.
- **vs (5) tree-sitter:** tree-sitter cannot emit the 6+ SABO edges
  that require name resolution. Disqualifying for SABO 2.0.
- **vs (6) srcML+srcType:** GPL-3.0 + dead.
- **vs (7) clangd LSP:** clangd is libclang behind an LSP server.
  We don't need the server overhead; cursor-level access is more
  ergonomic than parsing LSP responses.
- **vs (8) Joern c2cpg:** Joern is a heavier dependency (JVM + Scala
  toolchain + Joern release lifecycle) than `pip install libclang`;
  CPG → SABO mapper is 4–6k Scala vs 2.5–3.5k Python total; CPG
  schema doesn't have first-class `#include` edges; we'd inherit
  CPG-schema churn that has nothing to do with SABO.

The deciding criterion: every other competitive option (CDT, LibTooling,
clangd, c2cpg) ultimately wraps the same backend Clang or CDT does.
libclang Python is the thinnest bridge to that backend that still
exposes the full semantic surface, in the language the user already
uses for downstream analysis (M3GraphBuilder is Python).

### 3.2 What this stack does NOT solve

Be honest about three real limitations:

1. **Without `compile_commands.json`, name resolution degrades severely.**
   libclang falls back to scope-only resolution; cross-TU references
   become `__unresolved__`; macros expand wrong; standard headers may
   not be found. Plan: **require `compile_commands.json` by default**;
   provide a `--no-compile-commands` opt-out that prints a prominent
   warning ("running without compile_commands.json — type resolution
   will be incomplete") and falls back to per-file `index.parse()` with
   minimal flags. No SABO extractor for C/C++ can do better than this
   without solving the build-system-detection problem in general.

2. **macOS libclang loading.** The `libclang` PyPI wheel ships a
   bundled libclang.dylib. On macOS systems with Xcode + Homebrew LLVM
   installed, it occasionally picks the wrong one; users may need to
   set `LIBCLANG_PATH=/path/to/libclang.dylib`. Document this in the
   README. Linux is uniformly fine.

3. **Performance on multi-million-LOC codebases.** Python + libclang is
   adequate for typical project sizes (think LLVM-as-a-test would take
   hours, not minutes). If `cpppers` is ever asked to run on
   Chromium-scale inputs, swap the cursor-walk module for a LibTooling
   binary (option 4). The SABO output stays identical; only the
   internal walker changes.

### 3.3 Architecture sketch

Following the four reference extractors. Module layout (all paths
under `cpppers/`, mirroring `gophers/extractor/` and
`csharpers/Extractor/`):

```
cpppers/
├── cli.py              # argparse: <input-dir>, --name, --exclude (repeatable),
│                       #          --include-external, --output-dir,
│                       #          --format {cyjson,graphml,csv}, --no-compile-commands
├── defaults.py         # Default excludes (includes CMake/build dirs)
├── extractor.py        # Top-level pipeline: load CDB → walk TUs → emit graph
├── walker.py           # Cursor-kind dispatch; emits Node/Edge instances
├── vocabulary.py       # CursorKind → SABO label mapping
├── ids.py              # USR-based IDs for symbols; relative-path IDs for File/Folder
├── lpg/
│   ├── model.py        # Node, Edge, Graph dataclasses (lift from M3GraphBuilder/graphlib/graph.py)
│   ├── cyjson.py       # Cytoscape JSON codec (mirrors javapers' CyJsonCodec.kt:9-59)
│   ├── graphml.py      # GraphML codec
│   └── csv.py          # CSV codec
└── tests/
    ├── fixtures/       # Hand-written .h/.cpp/.c test inputs
    └── test_extractor.py
```

**CLI** (mirrors csharpers' `Program.cs:19-55` flag set, with the
universal SABO conventions):

```python
parser.add_argument("input_dir")
parser.add_argument("--name", required=True)
parser.add_argument("--exclude", action="append", default=[])
parser.add_argument("--include-external", action="store_true")
parser.add_argument("--output-dir", default="out")
parser.add_argument("--format", choices=["cyjson","graphml","csv"], default="cyjson")
parser.add_argument("--no-compile-commands", action="store_true")
parser.add_argument("--compile-commands-dir", default=None)  # defaults to <input-dir>/build
```

**Default excludes** (extending csharpers' `SourceOnlyCSharpGraphExtractor.cs:18-29`
with C/C++-specific build dirs):

```python
DEFAULT_EXCLUDES = [
    "bin","obj","target","build","dist","out","node_modules","vendor",
    ".git",".idea",".vs","Library","Temp",
    # C/C++ specific:
    "CMakeFiles","_deps","cmake-build-debug","cmake-build-release",
]
```

**ID convention.** For symbols (Type, Operation, Variable, Scope), use
`cursor.get_usr()` directly — clang's Unified Symbol Resolution is
deterministic, cross-TU stable, and hash-free (e.g.,
`c:@N@std@S@vector`). For File and Folder nodes, use the path
relative to the input root with forward slashes. This matches the
spec exactly: deterministic qualified name → ID.

**Two-phase extraction** (mirrors gophers's parse-then-resolve split):

```
Phase 1: For each TU in compile_commands.json,
         parse → walk cursors → buffer (cursor.get_usr(), kind, location, parents)
Phase 2: Build the symbol table keyed by USR
         Resolve cross-TU references (for `invokes`, `typed`, `specializes`, `instantiates`, `overrides`)
         Emit nodes (deduplicating by USR) and edges
Phase 3: Emit Project/Folder/File hierarchy from filesystem walk (with --exclude applied)
         Emit `contains`, `includes`, `encloses`, `declares` edges
```

### 3.4 How each gotcha is handled

| Gotcha | Approach |
|---|---|
| Header/implementation merging | One Type/Operation node per `cursor.get_usr()`. `cursor.get_definition()` canonicalizes a method declared in `Foo.h` and defined in `Foo.cpp` to the same USR. Emit `declares` edges from BOTH files (the header and the cpp); downstream visualization decides which to surface. |
| `#include` graph | `tu.get_includes()` returns `FileInclusion` objects with `source` and `include` paths; emit `File -includes-> File` edges with `kind: "include"` property. Don't conflate with semantic dependencies. |
| Templates | `CursorKind.CLASS_TEMPLATE` / `FUNCTION_TEMPLATE` → one Type/Operation node per template definition. Walk `cursor.get_children()` for `TEMPLATE_TYPE_PARAMETER` / `TEMPLATE_NON_TYPE_PARAMETER` → emit Variable nodes (kind="parameter") + `parameterizes` edges. Skip `CLASS_TEMPLATE_PARTIAL_SPECIALIZATION` (treat as separate Type with `specializes` edge to primary). Do NOT emit a node per instantiation. |
| Forward declarations | `cursor.get_definition()` returns the definition cursor (or self if no separate definition exists). Index by the USR of the definition; the forward decl and the definition share a USR by clang's design. |
| Macros | Skip from SABO graph entirely (per spec). Walked code is already macro-expanded by the preprocessor before libclang sees it. |
| Anonymous namespaces / structs | `cursor.spelling` is empty; fall back to `<file-relpath>::anon@<line>:<col>` using `cursor.location`. Include this in the USR-fallback path; libclang's USR for anonymous entities already encodes location, so usually `cursor.get_usr()` suffices. |
| `typedef` / `using` aliases | `CursorKind.TYPEDEF_DECL` / `TYPE_ALIAS_DECL` → emit Type node with `properties.kind = "alias"`. Emit `typed` edge to the underlying type via `cursor.underlying_typedef_type` (resolve via `Type.get_canonical()` then look up the cursor's USR). |
| C vs C++ | The same `cindex` API handles both. Detect from `compile_commands.json` flags (`-x c` vs `-x c++`) or fall back to file extension. Pure C exercises a smaller subset of SABO edges (no `specializes`, no `overrides`, no nested types, no templates) — this is normal, not a bug. |
| `compile_commands.json` | Loaded via `clang.cindex.CompilationDatabase.fromDirectory(<build-dir>)`; per-file flags via `getCompileCommands(file_path)`. Required by default; opt-out via `--no-compile-commands` with a loud warning. |
| External-symbol policy | Default: skip cursors where `cursor.location.file is None` (i.e., system or external). With `--include-external`: emit them and tag `properties.external = true`, matching the convention from `csharpers' SourceOnlyCSharpGraphExtractor.cs:137,174,240,270`. |

### 3.5 Migration path from the WIP

| Artifact | Disposition |
|---|---|
| `Cmake-parser-rascal/` (Alpha CMake parser) | **Discard.** Replaced by `compile_commands.json`. CMake projects emit it via `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`; document this in the README. |
| `alpha-rascal/` (CLAIR usage, M3 emission) | **Discard.** libclang replaces CLAIR. M3 JSON intermediate is eliminated. |
| `M3GraphBuilder/converters/cpp.py` | **Discard.** All M3-fragment-specific. |
| `M3GraphBuilder/converters/m3_utils.py` | **Discard.** Parses Rascal-specific URI schemes (`cpp+class:///…`) we no longer have. |
| `M3GraphBuilder/graphlib/graph.py` | **Reuse.** Node/Edge dataclasses, deduplication-by-ID logic, graph-composition operators are language-neutral and Python. Rename to `cpppers/lpg/model.py` and align with the Cytoscape JSON shape. |
| `M3GraphBuilder/graphlib/validator.py` | **Reuse partial.** Referential-integrity check is useful; rewrite the fragile `missing_ids.remove(missing_ids[0])` (validator.py:28) properly. |
| `M3GraphBuilder/graphlib/arvisaninator.py` | **Defer.** Hierarchy collapsing is downstream-visualization concern (per task spec); not in scope for the extractor. Keep around if/when needed. |
| `M3GraphBuilder/graphlib/merge_graph.py` | **Defer.** Multi-graph merging is a separate tool. |
| Vocabulary mapping decisions | **Re-derive.** SABO 1.0 → 2.0 is enough of a label-set change that translating WIP labels misleads more than it helps. Use `javapers`/`csharpers` as the reference. |
| Test fixtures | **Write fresh.** Neither WIP repo has any. Hand-author small `.h`/`.cpp`/`.c` programs covering each gotcha (header/impl split, templates, forward decl, anonymous namespace, typedef, etc.). |

---

## 4. Open questions for you

1. **`compile_commands.json` policy.** I'm proposing it be **required by
   default**, with `--no-compile-commands` as an opt-out that prints a
   prominent warning. The alternative is silent fallback. Recommend
   required-by-default because the SABO graph from a no-CDB run is
   misleadingly incomplete, and we'd rather fail loudly than emit a
   partial graph that looks complete. Confirm or override.

2. **`--include-external` scope for C/C++.** With libclang and a
   `compile_commands.json`, "external" includes the entire C++ standard
   library, every transitive header, libc, and any third-party headers
   in the include path. That can be tens of thousands of nodes. Three
   reasonable definitions of "external":
   - (a) Anything whose canonical file is outside the input directory
     (matches `csharpers` semantics, can produce huge graphs).
   - (b) Anything in a system include path (`-isystem` or default
     toolchain dirs) — excludes vendored third-party but includes libc/STL.
   - (c) Anything not in the input directory AND not in
     `compile_commands.json`'s working directories (excludes both
     system headers and vendored third-party).
   Recommend (b) as the default. Confirm or override.

3. **C++ standard fallback when no `compile_commands.json`.** libclang
   defaults to `-std=c++11` when invoked without flags. Modern projects
   are commonly C++17/20/23. Should `--no-compile-commands` accept a
   `--std=c++NN` flag? Recommend yes, defaulting to `c++20`.

4. **Macro-expansion side-effects.** Per the gotcha rules, macros are
   skipped from SABO. But macro-expanded code can synthesize identifiers
   that have no declaration in source (e.g., `#define DEFINE_FOO_GETTER`
   that emits a method). libclang sees the expanded form, so we'd emit
   a method with a synthesized location. Acceptable, or should we tag
   such cursors with `properties.macro_synthesized = true`? Recommend
   tagging — it's cheap and downstream consumers can filter.

5. **Repo-naming.** I've assumed the new repo/tool is named `cpppers`
   (matching the `*pers` family). Confirm.
