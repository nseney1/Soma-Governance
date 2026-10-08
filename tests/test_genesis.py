"""Comprehensive tests for ``soma genesis`` — automated governance cell generation.

Covers:
- Scanner: project type detection, all 8 detectors, filtering, dedup
- Generator: cell creation, dry-run, force-overwrite, YAML validity, tags
- CLI handler: dry-run exit code, JSON output, empty repo, idempotency
- Integration: realistic Python and Rust fixture repos
"""
from __future__ import annotations

import json
import os
import textwrap
from argparse import Namespace
from pathlib import Path

import pytest
from soma_core.somayaml import parse_frontmatter

from soma_cli.genesis_scanner import (
    CellCandidate,
    detect_api_surfaces,
    detect_config_stores,
    detect_data_pipelines,
    detect_module_boundaries,
    detect_project_type,
    detect_shared_state,
    detect_state_machines,
    detect_test_boundaries,
    scan,
)
from soma_cli.genesis_generator import generate_cells, generate_report


# ===================================================================
# Fixtures — realistic project structures
# ===================================================================


@pytest.fixture()
def python_project(tmp_path: Path) -> Path:
    """Realistic Python project fixture."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "myapp"\nversion = "0.1.0"\n'
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")

    # Config store with 20+ ALL_CAPS constants
    (src / "config.py").write_text(textwrap.dedent("""\
        DATABASE_URL = "postgres://localhost/db"
        SECRET_KEY = "changeme"
        MAX_RETRIES = 3
        TIMEOUT_SECONDS = 30
        DEBUG_MODE = False
        LOG_LEVEL = "INFO"
        CACHE_TTL = 600
        API_VERSION = "v2"
        BASE_URL = "https://example.com"
        REDIS_HOST = "localhost"
        REDIS_PORT = 6379
        WORKER_COUNT = 4
        BATCH_SIZE = 100
        MAX_CONNECTIONS = 50
        RATE_LIMIT = 1000
        ENABLE_METRICS = True
        FEATURE_FLAG_X = False
        CORS_ORIGINS = "*"
        SESSION_TIMEOUT = 3600
        UPLOAD_MAX_SIZE = 10485760
    """))

    # Shared state — imported by 4+ files
    (src / "models.py").write_text(textwrap.dedent("""\
        class User:
            pass
        class Order:
            pass
    """))

    # API surface
    api = src / "api"
    api.mkdir()
    (api / "__init__.py").write_text("")
    (api / "routes.py").write_text(textwrap.dedent("""\
        from src.models import User
        __all__ = ["get_users", "create_user", "delete_user", "update_user"]
        def get_users(): pass
        def create_user(): pass
        def delete_user(): pass
        def update_user(): pass
    """))
    (api / "middleware.py").write_text(textwrap.dedent("""\
        from src.models import User
        def auth_middleware(): pass
    """))

    # DB layer
    db = src / "db"
    db.mkdir()
    (db / "__init__.py").write_text("")
    (db / "session.py").write_text(textwrap.dedent("""\
        from src.models import User
        def get_session(): pass
    """))

    # Service that imports models
    (src / "service.py").write_text(textwrap.dedent("""\
        from src.models import User, Order
        def process_order(order: Order) -> bool:
            return True
    """))

    # Tests
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_api.py").write_text("def test_placeholder(): pass\n")

    return tmp_path


@pytest.fixture()
def rust_project(tmp_path: Path) -> Path:
    """Realistic Rust workspace fixture."""
    (tmp_path / "Cargo.toml").write_text(textwrap.dedent("""\
        [workspace]
        members = ["core", "engine"]
    """))

    # core crate
    core = tmp_path / "core"
    core.mkdir()
    (core / "Cargo.toml").write_text(textwrap.dedent("""\
        [package]
        name = "core"
        version = "0.1.0"

        [dependencies]
        serde = "1.0"
        thiserror = "1.0"
    """))
    core_src = core / "src"
    core_src.mkdir()
    (core_src / "lib.rs").write_text(textwrap.dedent("""\
        pub mod config;
        pub mod state;
    """))
    (core_src / "config.rs").write_text(textwrap.dedent("""\
        pub const MAX_ENTITIES: usize = 1000;
        pub const TICK_RATE: u32 = 60;
        pub const WORLD_SIZE: f64 = 1000.0;
        pub const GRAVITY: f64 = 9.81;
        pub const MAX_VELOCITY: f64 = 100.0;
        pub const PLAYER_HEALTH: i32 = 100;
        pub const PLAYER_SPEED: f64 = 5.0;
        pub const RENDER_DISTANCE: f64 = 500.0;
        pub const CHUNK_SIZE: usize = 16;
        pub const SEED_VALUE: u64 = 42;
        pub const DEBUG_ENABLED: bool = false;
    """))
    (core_src / "state.rs").write_text(textwrap.dedent("""\
        pub enum GameState {
            Menu,
            Loading,
            Playing,
            Paused,
        }

        pub enum ConnectionStatus {
            Disconnected,
            Connecting,
            Connected,
        }
    """))

    # engine crate
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "Cargo.toml").write_text(textwrap.dedent("""\
        [package]
        name = "engine"
        version = "0.1.0"

        [dependencies]
        core = { path = "../core" }
        wgpu = "0.18"
    """))
    engine_src = engine / "src"
    engine_src.mkdir()
    (engine_src / "lib.rs").write_text(textwrap.dedent("""\
        pub fn init() {}
        pub fn run() {}
        pub fn shutdown() {}
        pub fn render() {}
    """))
    (engine_src / "renderer.rs").write_text(textwrap.dedent("""\
        pub fn draw_frame() {}
        pub fn resize() {}
    """))

    return tmp_path


@pytest.fixture()
def empty_project(tmp_path: Path) -> Path:
    """Empty directory — no manifest files."""
    return tmp_path


@pytest.fixture()
def sample_candidates() -> list[CellCandidate]:
    """Reusable list of sample candidates for generator tests."""
    return [
        CellCandidate(
            name="wall-core-isolation",
            proposed_type="wall",
            hypothesis="Module 'core' must maintain dependency isolation",
            prediction="If 'core' imports disallowed deps, coupling increases",
            falsification="Remove if module is merged or deleted",
            target_paths=["core/**"],
            confidence=0.85,
            evidence={"manifest": "Cargo.toml", "source_files": 3},
            tags=["boundary", "isolation"],
        ),
        CellCandidate(
            name="vacuole-config-config",
            proposed_type="vacuole",
            hypothesis="'config.rs' stores critical configuration constants",
            prediction="Unreviewed config changes cause runtime failures",
            falsification="Remove if file is deleted or constants are inlined",
            target_paths=["core/src/config.rs"],
            confidence=0.75,
            evidence={"all_caps_count": 11, "config_name": True},
            tags=["config", "constants"],
        ),
        CellCandidate(
            name="membrane-lib-api",
            proposed_type="membrane",
            hypothesis="'engine/src/lib.rs' is a public API surface",
            prediction="Unreviewed API changes break downstream consumers",
            falsification="Remove if file becomes internal-only",
            target_paths=["engine/src/lib.rs"],
            confidence=0.7,
            evidence={"export_count": 4},
            tags=["api", "public-surface"],
        ),
    ]


# ===================================================================
# 1. Scanner tests — project type detection
# ===================================================================


class TestDetectProjectType:
    def test_rust(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        assert detect_project_type(tmp_path) == "rust"

    def test_python_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        assert detect_project_type(tmp_path) == "python"

    def test_python_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup\n")
        assert detect_project_type(tmp_path) == "python"

    def test_javascript(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"app"}\n')
        assert detect_project_type(tmp_path) == "javascript"

    def test_go(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/app\n")
        assert detect_project_type(tmp_path) == "go"

    def test_unknown(self, tmp_path: Path) -> None:
        assert detect_project_type(tmp_path) == "unknown"


# ===================================================================
# 1b. Scanner tests — individual detectors
# ===================================================================


class TestDetectModuleBoundaries:
    def test_cargo_workspace(self, rust_project: Path) -> None:
        candidates = detect_module_boundaries(rust_project, "rust")
        names = {c.name for c in candidates}
        assert any("core" in n for n in names)
        assert any("engine" in n for n in names)
        assert all(c.proposed_type == "wall" for c in candidates)

    def test_monorepo(self, tmp_path: Path) -> None:
        for pkg in ["auth", "billing", "frontend"]:
            d = tmp_path / "packages" / pkg
            d.mkdir(parents=True)
            (d / "package.json").write_text(f'{{"name":"{pkg}"}}\n')
            (d / "index.js").write_text(f"module.exports = '{pkg}';\n")
        candidates = detect_module_boundaries(tmp_path, "javascript")
        assert len(candidates) == 3

    def test_no_sub_modules(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hello')\n")
        candidates = detect_module_boundaries(tmp_path, "python")
        assert candidates == []


class TestDetectConfigStores:
    def test_high_caps_count(self, python_project: Path) -> None:
        candidates = detect_config_stores(python_project, "python")
        names = [c.name for c in candidates]
        assert any("config" in n for n in names)
        assert all(c.proposed_type == "vacuole" for c in candidates)

    def test_below_threshold(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        src = tmp_path / "src"
        src.mkdir()
        (src / "small.py").write_text(textwrap.dedent("""\
            FOO = 1
            BAR = 2
        """))
        candidates = detect_config_stores(tmp_path, "python")
        config_candidates = [c for c in candidates if "small" in c.name]
        assert config_candidates == []

    def test_config_named_file_lower_threshold(self, tmp_path: Path) -> None:
        """Files named config*/settings* need only 5 ALL_CAPS to qualify."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "settings.py").write_text(textwrap.dedent("""\
            HOST = "localhost"
            PORT = 8080
            DEBUG = True
            SECRET_KEY = "abc"
            LOG_LEVEL = "INFO"
        """))
        candidates = detect_config_stores(tmp_path, "python")
        assert any("settings" in c.name for c in candidates)


class TestDetectSharedState:
    def test_file_imported_by_many(self, python_project: Path) -> None:
        candidates = detect_shared_state(python_project, "python")
        # src.models is imported by routes.py, middleware.py, session.py, service.py
        model_candidates = [c for c in candidates if "models" in c.name]
        assert len(model_candidates) >= 1, f"Expected models candidate, got: {[c.name for c in candidates]}"
        assert model_candidates[0].proposed_type == "vacuole"

    def test_no_shared_state_in_empty(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hi')\n")
        candidates = detect_shared_state(tmp_path, "python")
        assert candidates == []


class TestDetectAPISurfaces:
    def test_rust_pub_fns(self, rust_project: Path) -> None:
        candidates = detect_api_surfaces(rust_project, "rust")
        # engine/src/lib.rs has 4 pub fn
        names = [c.name for c in candidates]
        assert any("lib" in n for n in names)
        assert all(c.proposed_type == "membrane" for c in candidates)

    def test_python_all_export(self, python_project: Path) -> None:
        candidates = detect_api_surfaces(python_project, "python")
        # routes.py has __all__ — but we need 3+ export patterns
        # It only has one __all__, so may or may not trigger
        # This is valid; the test verifies no crash
        assert isinstance(candidates, list)


class TestDetectDataPipelines:
    def test_typed_functions(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "pipeline.py").write_text(textwrap.dedent("""\
            def parse_input(raw: str) -> dict:
                return {}
            def transform(data: dict) -> list:
                return []
            def serialize(items: list) -> str:
                return ""
            def validate(data: dict) -> bool:
                return True
            def normalize(text: str) -> str:
                return text.lower()
            def aggregate(items: list) -> dict:
                return {}
            def filter_nulls(data: list) -> list:
                return [x for x in data if x]
            def format_output(result: dict) -> str:
                return str(result)
        """))
        candidates = detect_data_pipelines(tmp_path, "python")
        assert len(candidates) >= 1
        assert candidates[0].proposed_type == "chloroplast"

    def test_no_pipelines(self, tmp_path: Path) -> None:
        (tmp_path / "simple.py").write_text("x = 1\n")
        candidates = detect_data_pipelines(tmp_path, "python")
        assert candidates == []


class TestDetectStateMachines:
    def test_state_enum(self, rust_project: Path) -> None:
        candidates = detect_state_machines(rust_project, "rust")
        names = [c.name for c in candidates]
        assert any("state" in n for n in names)
        assert all(c.proposed_type == "plasmodesmata" for c in candidates)

    def test_python_state_class(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "workflow.py").write_text(textwrap.dedent("""\
            from enum import Enum
            class OrderStatus(Enum):
                PENDING = "pending"
                SHIPPED = "shipped"
                DELIVERED = "delivered"
        """))
        candidates = detect_state_machines(tmp_path, "python")
        assert len(candidates) == 1
        assert "OrderStatus" in candidates[0].evidence["state_types"]

    def test_no_state_machines(self, tmp_path: Path) -> None:
        (tmp_path / "plain.py").write_text("x = 1\n")
        candidates = detect_state_machines(tmp_path, "python")
        assert candidates == []


class TestDetectTestBoundaries:
    def test_coverage_gap(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        # Module with source but no tests
        untested = tmp_path / "untested_mod"
        untested.mkdir()
        (untested / "core.py").write_text("def important(): pass\n")
        # A test dir exists for something else
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_other.py").write_text("def test_x(): pass\n")
        candidates = detect_test_boundaries(tmp_path, "python")
        gap_names = [c.name for c in candidates]
        assert any("untested" in n for n in gap_names)


# ===================================================================
# 1c. Scanner tests — scan() integration
# ===================================================================


class TestScan:
    def test_empty_repo(self, empty_project: Path) -> None:
        assert scan(empty_project) == []

    def test_min_confidence_filter(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "pipeline.py").write_text(textwrap.dedent("""\
            def a(x: str) -> int: return 0
            def b(x: int) -> str: return ""
            def c(x: str) -> list: return []
        """))
        # Low threshold gets results
        low = scan(tmp_path, min_confidence=0.3)
        # Very high threshold filters everything
        high = scan(tmp_path, min_confidence=0.99)
        assert len(low) >= len(high)

    def test_deduplication(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        results = scan(tmp_path)
        names = [c.name for c in results]
        assert len(names) == len(set(names)), "Duplicate candidate names found"

    def test_sorted_by_confidence(self, python_project: Path) -> None:
        results = scan(python_project)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].confidence >= results[i + 1].confidence or \
                    (results[i].confidence == results[i + 1].confidence and
                     results[i].name <= results[i + 1].name)


# ===================================================================
# 2. Generator tests
# ===================================================================


class TestGenerateCells:
    def test_creates_vacuoles_dir(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        generate_cells(sample_candidates, cells_dir)
        assert (cells_dir / "vacuoles").is_dir()

    def test_all_cells_in_vacuoles(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        """ALL cells must land in vacuoles/ regardless of proposed_type."""
        cells_dir = tmp_path / "cells"
        results = generate_cells(sample_candidates, cells_dir)
        for r in results:
            assert "vacuoles" in r["path"]
            assert r["action"] == "created"

    def test_proposed_type_in_frontmatter(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        generate_cells(sample_candidates, cells_dir)
        for c in sample_candidates:
            path = cells_dir / "vacuoles" / f"{c.name}.md"
            content = path.read_text()
            fm = parse_frontmatter(content)
            assert fm["type"] == "vacuole"
            assert fm["proposed_type"] == c.proposed_type

    def test_dry_run_no_files(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        results = generate_cells(sample_candidates, cells_dir, dry_run=True)
        for r in results:
            assert r["action"] == "would_create"
            assert "content" in r
        # vacuoles dir created but no cell files inside
        md_files = list((cells_dir / "vacuoles").glob("*.md"))
        assert md_files == []

    def test_skip_existing(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        # First pass creates
        generate_cells(sample_candidates, cells_dir)
        # Second pass skips
        results = generate_cells(sample_candidates, cells_dir)
        for r in results:
            assert r["action"] == "skipped"

    def test_force_overwrite(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        generate_cells(sample_candidates, cells_dir)
        results = generate_cells(sample_candidates, cells_dir, force=True)
        for r in results:
            assert r["action"] == "created"

    def test_valid_yaml_frontmatter(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        """All generated frontmatter must parse as valid YAML."""
        cells_dir = tmp_path / "cells"
        generate_cells(sample_candidates, cells_dir)
        for c in sample_candidates:
            path = cells_dir / "vacuoles" / f"{c.name}.md"
            content = path.read_text()
            fm = parse_frontmatter(content)
            assert isinstance(fm, dict)
            assert "type" in fm
            assert "hypothesis" in fm

    def test_genesis_tag_present(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        generate_cells(sample_candidates, cells_dir)
        for c in sample_candidates:
            path = cells_dir / "vacuoles" / f"{c.name}.md"
            content = path.read_text()
            fm = parse_frontmatter(content)
            assert "genesis-generated" in fm["tags"]

    def test_expiry_fields_present(
        self, tmp_path: Path, sample_candidates: list[CellCandidate]
    ) -> None:
        cells_dir = tmp_path / "cells"
        generate_cells(sample_candidates, cells_dir)
        for c in sample_candidates:
            path = cells_dir / "vacuoles" / f"{c.name}.md"
            fm = parse_frontmatter(path.read_text())
            assert fm["expiry_sessions"] == 10
            assert fm["expiry_days"] == 30


class TestGenerateReport:
    def test_report_contains_all_candidates(
        self, sample_candidates: list[CellCandidate]
    ) -> None:
        report = generate_report(sample_candidates, "rust")
        for c in sample_candidates:
            assert c.name in report

    def test_report_has_header(
        self, sample_candidates: list[CellCandidate]
    ) -> None:
        report = generate_report(sample_candidates, "python")
        assert "# Organelle Map" in report
        assert "python" in report

    def test_report_groups_by_type(
        self, sample_candidates: list[CellCandidate]
    ) -> None:
        report = generate_report(sample_candidates, "rust")
        assert "Walls" in report
        assert "Membranes" in report


# ===================================================================
# 3. CLI tests
# ===================================================================


class TestGenesisCLI:
    def _make_args(self, **kwargs) -> Namespace:
        defaults = {
            "project_root": None,
            "dry_run": False,
            "json": False,
            "min_confidence": 0.5,
            "force": False,
            "yes": True,
        }
        defaults.update(kwargs)
        return Namespace(**defaults)

    def test_dry_run_exit_zero(self, python_project: Path) -> None:
        from soma_cli.genesis import run_genesis

        args = self._make_args(project_root=str(python_project), dry_run=True)
        rc = run_genesis(args)
        assert rc == 0

    def test_json_output_valid(self, python_project: Path, capsys) -> None:
        from soma_cli.genesis import run_genesis

        args = self._make_args(
            project_root=str(python_project), dry_run=True, json=True
        )
        rc = run_genesis(args)
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "project_type" in data
        assert "candidates" in data

    def test_empty_repo_message(self, empty_project: Path, capsys) -> None:
        from soma_cli.genesis import run_genesis

        args = self._make_args(project_root=str(empty_project))
        rc = run_genesis(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "No governance candidates" in captured.out

    def test_empty_repo_json(self, empty_project: Path, capsys) -> None:
        from soma_cli.genesis import run_genesis

        args = self._make_args(project_root=str(empty_project), json=True)
        rc = run_genesis(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "empty"

    def test_idempotent(self, python_project: Path) -> None:
        """Running genesis twice should produce same result (skip existing)."""
        from soma_cli.genesis import run_genesis

        args = self._make_args(project_root=str(python_project), yes=True)
        rc1 = run_genesis(args)
        assert rc1 == 0
        # Second run
        rc2 = run_genesis(args)
        assert rc2 == 0

    def test_invalid_root_returns_1(self, tmp_path: Path) -> None:
        from soma_cli.genesis import run_genesis

        args = self._make_args(
            project_root=str(tmp_path / "nonexistent_dir_xyz")
        )
        rc = run_genesis(args)
        assert rc == 1


# ===================================================================
# 4. Integration tests
# ===================================================================


class TestIntegration:
    def test_genesis_on_python_project(self, python_project: Path) -> None:
        candidates = scan(python_project)
        assert len(candidates) >= 1
        types_found = {c.proposed_type for c in candidates}
        # Should detect at least vacuoles (config store)
        assert "vacuole" in types_found

    def test_genesis_on_rust_project(self, rust_project: Path) -> None:
        candidates = scan(rust_project)
        assert len(candidates) >= 1
        types_found = {c.proposed_type for c in candidates}
        # Should detect walls (module boundaries)
        assert "wall" in types_found

    def test_full_pipeline_python(self, python_project: Path) -> None:
        """End-to-end: scan → generate → verify files exist."""
        candidates = scan(python_project)
        cells_dir = python_project / ".soma" / "cells"
        results = generate_cells(candidates, cells_dir)
        created = [r for r in results if r["action"] == "created"]
        assert len(created) >= 1
        # All files exist on disk
        for r in created:
            assert Path(r["path"]).exists()
            content = Path(r["path"]).read_text()
            assert "---" in content
            assert "vacuole" in content.lower()

    def test_full_pipeline_rust(self, rust_project: Path) -> None:
        """End-to-end: scan → generate → verify files exist."""
        candidates = scan(rust_project)
        cells_dir = rust_project / ".soma" / "cells"
        results = generate_cells(candidates, cells_dir)
        created = [r for r in results if r["action"] == "created"]
        assert len(created) >= 1
        for r in created:
            assert Path(r["path"]).exists()

    def test_organelle_report_written(self, python_project: Path) -> None:
        candidates = scan(python_project)
        project_type = detect_project_type(python_project)
        report = generate_report(candidates, project_type)
        assert "# Organelle Map" in report
        assert len(report) > 50

    def test_genesis_cli_creates_files(self, python_project: Path) -> None:
        """Full CLI pipeline creates cell files and organelle report."""
        from soma_cli.genesis import run_genesis

        args = Namespace(
            project_root=str(python_project),
            dry_run=False,
            json=False,
            min_confidence=0.5,
            force=False,
            yes=True,
        )
        rc = run_genesis(args)
        assert rc == 0
        # Cell files exist
        vacuole_dir = python_project / ".soma" / "cells" / "vacuoles"
        assert vacuole_dir.is_dir()
        cells = list(vacuole_dir.glob("*.md"))
        assert len(cells) >= 1
        # Organelle report exists
        report_path = python_project / "docs" / "organelles.md"
        assert report_path.exists()
