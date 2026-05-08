"""End-to-end integration tests for the extractor + CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

cindex = pytest.importorskip("clang.cindex")

from cpppers.cli import main as cli_main
from cpppers.extractor import ExtractorOptions, extract


def _scaffold_simple_project(tmp_path: Path) -> Path:
    """A small but realistic C++ project covering the major SABO labels."""
    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "include").mkdir()
    (proj / "src").mkdir()
    (proj / "include" / "shape.h").write_text(
        """
        #pragma once
        namespace demo {
            class Shape {
            public:
                virtual int area() const = 0;
                virtual ~Shape() {}
            };
            class Square : public Shape {
                int side_;
            public:
                explicit Square(int s) : side_(s) {}
                int area() const override { return side_ * side_; }
            };
        }
        """
    )
    (proj / "src" / "main.cpp").write_text(
        '''
        #include "shape.h"
        namespace demo {
            int total() {
                Square s(4);
                return s.area();
            }
        }
        '''
    )
    return proj


def test_extract_runs_without_cdb_and_produces_expected_labels(tmp_path):
    proj = _scaffold_simple_project(tmp_path)
    options = ExtractorOptions(
        input_dir=str(proj),
        project_name="demo",
        no_compile_commands=True,
    )
    graph = extract(options)

    label_set = set()
    for n in graph.nodes:
        label_set.update(n.labels)
    edge_labels = {e.label for e in graph.edges}

    # Every SABO 2.0 node label that's emittable from this fixture.
    for label in ("Project", "Folder", "File", "Scope", "Type", "Operation", "Variable"):
        assert label in label_set, f"missing node label: {label}"

    # Edges we should observe: contains, declares, encloses, encapsulates,
    # specializes, overrides, invokes, instantiates, includes.
    for label in (
        "contains",
        "declares",
        "encloses",
        "encapsulates",
        "specializes",
        "overrides",
        "invokes",
        "instantiates",
        "includes",
    ):
        assert label in edge_labels, f"missing edge label: {label}"


def test_extract_requires_cdb_by_default(tmp_path):
    """§4 q1: required by default; failing-loud message should mention the path."""
    proj = _scaffold_simple_project(tmp_path)
    options = ExtractorOptions(input_dir=str(proj), project_name="demo")
    with pytest.raises(FileNotFoundError) as ei:
        extract(options)
    msg = str(ei.value)
    assert "compile_commands.json" in msg
    assert "--no-compile-commands" in msg


def test_extract_loads_a_real_cdb(tmp_path):
    proj = _scaffold_simple_project(tmp_path)
    src = proj / "src" / "main.cpp"
    cdb = proj / "compile_commands.json"
    cdb.write_text(
        json.dumps(
            [
                {
                    "directory": str(proj),
                    "file": str(src),
                    "arguments": [
                        "/usr/bin/clang++",
                        "-std=c++20",
                        f"-I{proj / 'include'}",
                        "-c",
                        str(src),
                    ],
                }
            ]
        )
    )
    graph = extract(ExtractorOptions(input_dir=str(proj), project_name="demo"))
    # Square node should be present (proves the include path was honoured).
    type_names = {
        n.properties.get("simpleName")
        for n in graph.nodes
        if "Type" in n.labels
    }
    assert "Square" in type_names
    assert "Shape" in type_names


def test_cli_writes_cyjson_output(tmp_path, capsys):
    proj = _scaffold_simple_project(tmp_path)
    out = tmp_path / "outdir"
    rc = cli_main(
        [
            str(proj),
            "--name",
            "demo",
            "--no-compile-commands",
            "--output-dir",
            str(out),
        ]
    )
    assert rc == 0
    json_path = out / "demo.json"
    assert json_path.is_file()
    payload = json.loads(json_path.read_text())
    assert "elements" in payload
    assert payload["elements"]["nodes"]
    assert payload["elements"]["edges"]


def test_cli_writes_graphml_output(tmp_path):
    proj = _scaffold_simple_project(tmp_path)
    out = tmp_path / "outdir"
    rc = cli_main(
        [
            str(proj),
            "--name",
            "demo",
            "--no-compile-commands",
            "--output-dir",
            str(out),
            "--format",
            "graphml",
        ]
    )
    assert rc == 0
    assert (out / "demo.graphml").is_file()


def test_cli_writes_csv_pair(tmp_path):
    proj = _scaffold_simple_project(tmp_path)
    out = tmp_path / "outdir"
    rc = cli_main(
        [
            str(proj),
            "--name",
            "demo",
            "--no-compile-commands",
            "--output-dir",
            str(out),
            "--format",
            "csv",
        ]
    )
    assert rc == 0
    assert (out / "demo-nodes.csv").is_file()
    assert (out / "demo-edges.csv").is_file()


def test_cli_returns_2_when_cdb_missing(tmp_path, capsys):
    proj = _scaffold_simple_project(tmp_path)
    rc = cli_main([str(proj), "--name", "demo", "--output-dir", str(tmp_path / "out")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "compile_commands.json" in err
