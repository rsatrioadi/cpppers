# cpppers

A SABO 2.0 source-code extractor for C and C++. Parses your project with
libclang, walks the cursor tree, and emits a labelled property graph
(LPG) for downstream visualisation in ClassViz / BubbleTeaViz / ARViSAN.

`cpppers` is the C/C++ counterpart of [`csharpers`](https://github.com/satrioadi/csharpers)
and [`javapers`](https://github.com/satrioadi/javapers); it follows the
same vocabulary and CLI conventions.

For the architectural rationale (why libclang-via-Python and not the
seven other candidates), see
[`cpppers-stack-recommendation.md`](./cpppers-stack-recommendation.md).

---

## Quick start

```bash
# 1. Install in development mode with test deps
pip install -e '.[test]'

# 2. Generate a compile_commands.json for your project
#    (CMake projects):
cmake -S /path/to/project -B /path/to/project/build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
#    (Make-based projects, via Bear):
bear -- make

# 3. Extract
cpppers /path/to/project --name my-project

# Output lands at ./out/my-project.json (Cytoscape JSON)
```

That's the happy path. If you don't have a `compile_commands.json`,
read the [Compile database](#compile-database-required-by-default)
section below — it's required by default and the tool will fail loud
if it's missing.

---

## Installation

### Requirements

* **Python 3.10 or later** (uses `match`/`|` type syntax sparingly).
* **libclang**. The PyPI `libclang` wheel bundles a copy for
  Linux-x86_64/arm64 and macOS-x86_64/arm64 — `pip install` is enough
  on those platforms. On Linux distros without a working wheel, install
  the system package (`libclang-dev` on Debian/Ubuntu,
  `clang-libs` on Fedora) and point `LIBCLANG_PATH` at the resulting
  `.so` / `.dylib`.

### Install for use

```bash
pip install -e .
```

This puts a `cpppers` console script on your `$PATH`.

### Install for development

```bash
pip install -e '.[test]'
pytest cpppers/tests/   # 59 tests, ~5s total
```

---

## CLI reference

```
cpppers <input_dir> --name <project_name> [options]
```

| Flag | Default | Description |
|---|---|---|
| `<input_dir>` | required | Project root (a directory containing C/C++ sources). |
| `--name NAME` | required | Project name; becomes the `Project` node id. |
| `--exclude GLOB` | (none) | Path glob (relative to `input_dir`) to skip. Repeatable. |
| `--include-external` | off | Emit symbols/files from outside `input_dir` (system headers, vendored deps). Off by default — see [External symbols](#external-symbols). |
| `--output-dir DIR` | `out` | Where to write output files. |
| `--format {cyjson, graphml, csv}` | `cyjson` | Output format. |
| `--no-compile-commands` | off | Run without `compile_commands.json`. Type resolution will be incomplete; a warning is printed. |
| `--compile-commands-dir DIR` | (auto) | Directory containing `compile_commands.json`. Defaults to `<input_dir>/build` then `<input_dir>`. |
| `--std=cxxNN` | `c++20` | C++ standard for fallback parses. Only used with `--no-compile-commands`. |
| `-v` / `-vv` | `WARNING` | Increase log verbosity. `-v` = INFO, `-vv` = DEBUG. |

### Examples

```bash
# Basic — auto-detect compile_commands.json under <project>/build/
cpppers ~/code/myproj --name myproj

# Custom output location and format
cpppers ~/code/myproj --name myproj \
    --output-dir ~/sabo-graphs \
    --format graphml

# Skip vendored / generated trees
cpppers ~/code/myproj --name myproj \
    --exclude 'third_party/**' \
    --exclude 'generated/**'

# CDB lives in a non-default location
cpppers ~/code/myproj --name myproj \
    --compile-commands-dir ~/code/myproj/cmake-build-release

# No CDB at all (smaller fidelity, useful for spike work)
cpppers ~/code/myproj --name myproj --no-compile-commands --std=c++17
```

---

## Compile database (required by default)

`cpppers` needs to know how each translation unit is compiled — which
headers to find, which macros to define, which language standard.
Without that information libclang falls back to scope-only resolution,
cross-TU references become `__unresolved__`, and standard headers may
not be found at all.

The tool requires a `compile_commands.json` by default. If it's not
present at `<input_dir>/build/compile_commands.json` or
`<input_dir>/compile_commands.json`, the run fails with this message:

```
compile_commands.json not found. Either:
  * place it at <input>/build/compile_commands.json or <input>/compile_commands.json,
  * pass --compile-commands-dir <dir>, or
  * pass --no-compile-commands (the SABO graph will be partial; type
    resolution will be incomplete).
```

### How to generate one

* **CMake**: configure with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`. The
  file lands in your build directory.
* **Make / autotools / hand-rolled**: install [Bear](https://github.com/rizsotto/Bear)
  and prefix your build command with `bear -- `. Example:
  `bear -- make -j8`.
* **Bazel**: use [`bazel-compile-commands-extractor`](https://github.com/hedronvision/bazel-compile-commands-extractor).
* **Meson**: it's emitted automatically into `<builddir>/compile_commands.json`.
* **Anything else**: write the JSON by hand. The schema is small —
  see the [Clang documentation](https://clang.llvm.org/docs/JSONCompilationDatabase.html).

### Running without one

`--no-compile-commands` is the escape hatch. The extractor will:

1. Print a prominent warning to stderr.
2. Synthesise minimal parse args per file: `-x c++ -std=c++20` for
   `.cpp`/`.cc`/etc., `-x c -std=c11` for `.c`. Override the C++
   standard with `--std=c++17` etc.
3. Auto-add `-I<input_dir>`, `-I<input_dir>/include`, and the source
   file's own directory to the include path so common project layouts
   keep working.

What you lose:

* Macros that depend on build-system-defined symbols won't expand
  correctly. Code under `#ifdef VENDOR_FEATURE` may be skipped.
* Vendored dependencies under non-standard include paths won't be found.
* External-vs-internal classification is less precise.

If you only need the structural skeleton (Project / Folder / File /
contains / includes), `--no-compile-commands` is fine. If you need the
type-system or call-graph edges to be trustworthy, generate a CDB.

---

## Output

### Cytoscape JSON (`--format cyjson`, default)

```json
{
  "elements": {
    "nodes": [
      {"data": {"id": "demo", "labels": ["Project"], "properties": {...}}},
      {"data": {"id": "src/foo.cpp", "labels": ["File"], "properties": {...}}},
      {"data": {"id": "c:@N@demo@S@Foo", "labels": ["Type"], "properties": {...}}}
    ],
    "edges": [
      {"data": {"id": "demo-contains-src/foo.cpp", "source": "demo", "target": "src/foo.cpp", "label": "contains", "properties": {"weight": 1}}}
    ]
  }
}
```

Drop straight into ClassViz / BubbleTeaViz.

### GraphML (`--format graphml`)

Standards-compliant XML with auto-derived `<key>` declarations. Open in
yEd, Gephi, or anything that speaks GraphML.

### CSV (`--format csv`)

Two files: `<name>-nodes.csv` and `<name>-edges.csv`. Property columns
are the union of all keys observed on the corresponding kind of element.
Suitable for ARViSAN and ad-hoc analysis in pandas / R / a spreadsheet.

---

## SABO 2.0 vocabulary emitted

### Node labels

| Label | What it represents | clang origin |
|---|---|---|
| `Project` | The project root | (synthesised) |
| `Folder` | Directory under the project root | (filesystem walk) |
| `File` | One source / header file | (filesystem walk + `tu.get_includes()`) |
| `Scope` | Namespace / translation-unit scope | `NAMESPACE`, `TRANSLATION_UNIT` |
| `Type` | Class, struct, union, enum, template, typedef, using-alias | `CLASS_DECL`, `STRUCT_DECL`, `UNION_DECL`, `ENUM_DECL`, `CLASS_TEMPLATE`, `TYPEDEF_DECL`, `TYPE_ALIAS_DECL` |
| `Operation` | Function, method, ctor/dtor, operator, conversion, function template | `FUNCTION_DECL`, `CXX_METHOD`, `CONSTRUCTOR`, `DESTRUCTOR`, `CONVERSION_FUNCTION`, `FUNCTION_TEMPLATE` |
| `Variable` | Field, parameter, local, global, enum constant, template parameter | `FIELD_DECL`, `PARM_DECL`, `VAR_DECL`, `ENUM_CONSTANT_DECL`, `TEMPLATE_*_PARAMETER` |

`Metric` is part of SABO 2.0 but `cpppers` doesn't emit metrics yet
(deferred — see [Roadmap](#roadmap)).

### Edge labels

| Label | Source → Target | Meaning |
|---|---|---|
| `contains` | Project / Folder → Folder / File | Filesystem hierarchy. |
| `includes` | File → File | `#include` directive (preprocessor). |
| `encloses` | Scope → Scope/Type/Operation/Variable; Type → Type | Lexical containment. |
| `declares` | File → Type/Operation/Variable/Scope | This file contains a declaration of the symbol. Both header and `.cpp` get a `declares` edge to a header/impl-merged node. |
| `encapsulates` | Type → Operation / Variable | Method or field bound to a class. |
| `parameterizes` | Variable → Type / Operation | Template parameter on a class/function template. |
| `returns` | Operation → Type | Function return type (only when the type is also in the graph). |
| `typed` | Variable → Type; Type(alias) → Type | Variable's declared type, or alias's underlying type. |
| `specializes` | Type → Type | Inheritance, or partial-spec → primary template. |
| `overrides` | Operation → Operation | Virtual override across class hierarchy. |
| `invokes` | Operation → Operation | Function call. |
| `uses` | Operation → Variable | Field / variable read or write. |
| `instantiates` | Operation → Type | Constructor call or `new` expression. |

### ID conventions

* **Symbols** (Type, Operation, Variable, Scope): `cursor.get_usr()`
  directly. USRs look like `c:@N@std@S@vector` or
  `c:@S@Foo@F@bar#I#`. They're deterministic, hash-free, and stable
  across translation units — header `Foo::bar()` and the `.cpp`
  definition collapse to one node automatically.
* **Files / Folders**: path relative to `<input_dir>`, with forward
  slashes. The Project node uses `--name`. The root folder gets the
  reserved id `.` so it doesn't collide with the Project.
* **Anonymous entities without a USR**: fall back to
  `<file>::anon@<line>:<col>`. Rarely fires — clang's USR encodes the
  location for anonymous entities.

---

## How gotchas are handled

A summary of the §3.4 table from the recommendation. Test fixtures for
each gotcha live in [`cpppers/tests/fixtures/gotchas/`](./cpppers/tests/fixtures/gotchas).

| Gotcha | Approach |
|---|---|
| Header / implementation merge | One node per `cursor.get_usr()`; `cursor.get_definition()` canonicalises forward decls. Both files get a `declares` edge to the merged node. |
| `#include` graph | `tu.get_includes()` → `File -includes-> File` with `kind: "include"`. Distinct from semantic dependencies. |
| Templates | One Type/Operation node per template definition. `parameterizes` edges from each template parameter. **No** node per instantiation. Partial specialisations are separate Types. |
| Forward declarations | Forward decl and definition share a USR by clang's design — automatic dedup. |
| Macros | Skipped from the graph entirely (per spec). Walked code is post-preprocessor. |
| Anonymous namespaces / structs | Clang's USR encodes the location, so `cursor.get_usr()` already disambiguates. Synthesised id `<file>::anon@<line>:<col>` is the rare fallback. |
| `typedef` / `using` aliases | `Type` node with `properties.kind = "alias"`, plus a `typed` edge to the underlying type. |
| C vs C++ | Same `cindex` API. Detected from `compile_commands.json` flags or file extension. C exercises a smaller subset of edges (no `specializes`, no `overrides`, no templates) — that's expected. |
| External symbols | Default: skip cursors whose file is outside `<input_dir>`. With `--include-external`, emit them with `properties.external = true`. |
| Macro-synthesised cursors | Tagged with `properties.macro_synthesized = true` so downstream tooling can filter. |

### External symbols

The current "external" definition is **option (b) from §4 q2 of the
recommendation**: anything whose declaring file is not under the input
directory. This excludes vendored third-party AND system headers; with
a real `compile_commands.json` that would otherwise pull in tens of
thousands of nodes from `libc` / STL / SDK headers.

If you need vendored deps in the graph but not the standard library,
configure your build to vendor them under `<input_dir>` (or a path
already covered by your includes), and they'll be picked up as internal.

---

## Architecture

A two-phase libclang walk per §3.3 of the recommendation:

```
Phase 1: Filesystem walk → Project / Folder / File / contains
         (cpppers/fs_walk.py)

Phase 2: For each TU in compile_commands.json,
         parse → walk cursors → buffer SymbolEntry tuples
         (cpppers/walker.py — _walk_one_translation_unit)

Phase 3: Build symbol table keyed by USR
         Pick canonical observation (definition wins)
         Emit one Node per USR
         Emit declares / encloses / encapsulates edges
         (cpppers/walker.py — emit_symbol_nodes)

Phase 4: Re-walk every TU to emit type-system + call edges
         (cpppers/edges.py — emit_semantic_edges)

Phase 5: Walk tu.get_includes() → File-includes-File
         (cpppers/includes.py — emit_include_edges)
```

Module layout:

```
cpppers/
├── cli.py                  # argparse entry point
├── extractor.py            # phase orchestration + ExtractorOptions
├── walker.py               # phase 1 + node-side phase 2
├── edges.py                # type-system + call-graph edges
├── includes.py             # #include graph
├── fs_walk.py              # Project / Folder / File / contains
├── cdb.py                  # compile_commands.json loader + fallback args
├── parsing.py              # Index.parse wrapper
├── vocabulary.py           # CursorKind → SABO label/kind mapping
├── ids.py                  # USR / relative-path id helpers
├── defaults.py             # exclude dirs, file extensions, default std
├── lpg/
│   ├── model.py            # Node, Edge, Graph (set semantics)
│   ├── cyjson.py           # Cytoscape JSON codec
│   ├── graphml.py          # GraphML codec
│   └── csv.py              # CSV codec (nodes + edges)
└── tests/
    ├── fixtures/gotchas/   # hand-authored .h/.cpp/.c covering each gotcha
    └── test_*.py
```

---

## Troubleshooting

### "compile_commands.json not found"

You haven't generated one yet. See [Compile database](#compile-database-required-by-default).
If you genuinely don't want one, pass `--no-compile-commands`.

### "fatal error: 'foo.h' file not found"

Your CDB is incomplete: an include path is missing. With a CMake-generated
CDB this almost always means your `target_include_directories(...)` list
is incomplete. With Bear, it usually means the build was incremental — try
a full clean rebuild under `bear -- make clean all`.

In `--no-compile-commands` mode, this happens when `#include "foo.h"`
points at a header that's neither alongside the source, nor under
`<input_dir>/include`, nor under `<input_dir>`. Either move the header
or generate a real CDB.

### macOS: "libclang.dylib not found" or wrong version loaded

The PyPI `libclang` wheel bundles a copy of `libclang.dylib`. On systems
with both Xcode Command Line Tools and Homebrew LLVM installed, the
wrong one occasionally gets picked. Pin the path:

```bash
export LIBCLANG_PATH=$(python3 -c "import libclang, os; print(os.path.dirname(libclang.__file__))")/native/libclang.dylib
# or, if you prefer the system one:
export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib
```

A smoke test confirms libclang is reachable: `pytest cpppers/tests/test_parsing_smoke.py`.

### Graphs are huge / mostly STL

You forgot to filter externals — that's the default. Re-run without
`--include-external`. If you genuinely want external content but not
the entire SDK, [§4 question 2 of the recommendation](./cpppers-stack-recommendation.md#4-open-questions-for-you)
discusses the trade-offs; the current build implements option (b) as
a hard policy.

### Performance: extraction is slow on large codebases

Python + libclang scales sub-linearly because each TU re-parses every
included header. Mitigations:

* Run on a focused subdirectory: `cpppers /repo/src/component --name component`.
* Aggressively `--exclude` test directories, generated code, and
  third-party.
* For multi-million-LOC codebases (Chromium-scale), the recommendation
  notes this stack hits its ceiling — see §3.2 limitation 3 for the
  LibTooling escape hatch.

---

## Development

### Running the tests

```bash
pip install -e '.[test]'
pytest cpppers/tests/                  # full suite
pytest cpppers/tests/test_lpg.py       # one module
pytest -k 'overrides'                  # by keyword
pytest cpppers/tests/test_parsing_smoke.py  # libclang smoke check
```

The fixture-driven gotcha tests use the canonical files under
`cpppers/tests/fixtures/gotchas/`. They're committed so a regression
is reproducible from a fresh clone — don't re-author them in tests.

### Test layout

| File | Scope |
|---|---|
| `test_lpg.py` | Node / Edge / Graph identity, set semantics, three codecs |
| `test_fs_walk.py` | Discovery, default excludes, user globs, Project/Folder/File emission |
| `test_cdb.py` | `compile_commands.json` parsing, arg-stripping, fallback args |
| `test_parsing_smoke.py` | libclang loadable on this machine; USR stability across decl/def |
| `test_walker_nodes.py` | Phase-1 buffering + phase-2 node/declares/encloses/encapsulates emission |
| `test_edges_semantic.py` | Type-system + call-graph edge families (one test per family) |
| `test_includes.py` | `#include` graph, dedup across TUs, external policy |
| `test_extractor_pipeline.py` | End-to-end CLI / pipeline integration |
| `test_fixtures_gotchas.py` | Each gotcha from §3.4 verified against committed fixtures |

### Adding a new edge family

1. Add a helper to `cpppers/edges.py` that takes
   `(graph, cursor, node, usr_to_node)` and emits the edges.
2. Wire it into `emit_semantic_edges` from the appropriate cursor-kind
   branch.
3. Pin the behaviour in `cpppers/tests/test_edges_semantic.py` with a
   focused fixture.

### Adding a new output codec

Add `cpppers/lpg/<name>.py` with `dumps(graph) -> str` and
`write(graph, path)` methods, export it from `cpppers/lpg/__init__.py`,
and wire it into `cpppers/cli.py` (the `--format` choices and the
`if fmt == ...` dispatch).

---

## Roadmap

* **Metrics**: emit `Metric` nodes (Halstead, McCabe, NumStatements)
  with `measures` edges. The shape is already in `lpg.model.Edge.properties`
  — needs a `cpppers/metrics/` package paralleling `csharpers/Metrics/`.
* **Validator**: port the referential-integrity checker from
  `M3GraphBuilder/graphlib/validator.py` (rewriting the fragile
  `missing_ids.remove(missing_ids[0])` properly per §3.5).
* **Parallelism**: parse N TUs in worker threads. libclang is
  thread-safe per index; this is mostly bookkeeping.
* **Better template-instantiation tracking**: emit `instantiates` from
  `Type X<int>` usages back to the template definition, not just from
  constructor calls.

---

## License

MIT. See `pyproject.toml`.

---

## Related projects

* [`csharpers`](https://github.com/satrioadi/csharpers) — same SABO
  vocabulary, C# / Roslyn backend.
* [`javapers`](https://github.com/satrioadi/javapers) — same vocabulary,
  Java / Spoon backend.
* The full design rationale that produced `cpppers` is in
  [`cpppers-stack-recommendation.md`](./cpppers-stack-recommendation.md).
