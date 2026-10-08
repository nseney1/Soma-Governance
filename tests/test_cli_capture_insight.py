"""TDD tests for `soma capture-insight` CLI porcelain command."""
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import pytest

from soma_cli.cli import _build_parser, main


class TestCaptureInsightCLI:
    def test_parser_registration(self):
        """Parser recognizes capture-insight and required flags."""
        parser = _build_parser()
        args = parser.parse_args([
            "capture-insight",
            "--insight", "Avoid raw socket allocations",
            "--context-files", "net/tcp.py", "net/udp.py",
            "--category", "networking",
            "--scaffold-wall",
            "--wall-id", "socket-safety",
        ])
        assert args.command == "capture-insight"
        assert args.insight == "Avoid raw socket allocations"
        assert args.context_files == ["net/tcp.py", "net/udp.py"]
        assert args.category == "networking"
        assert args.scaffold_wall is True
        assert args.wall_id == "socket-safety"

    def test_parser_requires_insight_and_context_files(self):
        """Missing --insight or --context-files causes parse failure."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["capture-insight", "--insight", "Something"])
        with pytest.raises(SystemExit):
            parser.parse_args(["capture-insight", "--context-files", "foo.py"])

    def test_run_capture_insight_basic(self, tmp_path):
        """Executing soma capture-insight appends to human_insights.jsonl."""
        ws = tmp_path
        (ws / ".soma").mkdir(parents=True)
        (ws / "core").mkdir(parents=True)
        (ws / "core" / "app.py").write_text("code", encoding="utf-8")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main([
                "capture-insight",
                "--workspace", str(ws),
                "--insight", "Check connection timeout",
                "--context-files", "core/app.py",
            ])

        assert exit_code == 0
        assert "Captured insight" in stdout.getvalue()

        jsonl_path = ws / ".soma" / "human_insights.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["insight"] == "Check connection timeout"
        assert record["context_files"] == ["core/app.py"]
        assert "wall_file" not in record

    def test_run_capture_insight_scaffold_wall(self, tmp_path):
        """Executing with --scaffold-wall and --wall-id creates wall markdown."""
        ws = tmp_path
        (ws / ".soma").mkdir(parents=True)
        (ws / "auth").mkdir(parents=True)
        (ws / "auth" / "jwt.py").write_text("token", encoding="utf-8")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main([
                "capture-insight",
                "--workspace", str(ws),
                "--insight", "Enforce asymmetric signatures for JWT verification",
                "--context-files", "auth/jwt.py",
                "--category", "security",
                "--scaffold-wall",
                "--wall-id", "jwt-asymmetric",
            ])

        assert exit_code == 0
        wall_file = ws / ".soma" / "cells" / "walls" / "wall-jwt-asymmetric.md"
        assert wall_file.exists()
        content = wall_file.read_text(encoding="utf-8")
        assert "id: wall-jwt-asymmetric" in content
        assert "type: wall" in content
        assert "Enforce asymmetric signatures" in content

    def test_run_capture_insight_json_output(self, tmp_path):
        """Executing with --json outputs valid JSON record."""
        ws = tmp_path
        (ws / ".soma").mkdir(parents=True)
        (ws / "lib").mkdir(parents=True)
        (ws / "lib" / "math.py").write_text("def add(): pass", encoding="utf-8")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main([
                "capture-insight",
                "--workspace", str(ws),
                "--insight", "Float division precision loss",
                "--context-files", "lib/math.py",
                "--json",
            ])

        assert exit_code == 0
        output_json = json.loads(stdout.getvalue())
        assert output_json["insight"] == "Float division precision loss"
        assert output_json["context_files"] == ["lib/math.py"]

    def test_run_capture_insight_format_json(self, tmp_path):
        """Executing with --format json outputs valid JSON record."""
        ws = tmp_path
        (ws / ".soma").mkdir(parents=True)
        (ws / "lib").mkdir(parents=True)
        (ws / "lib" / "math.py").write_text("def add(): pass", encoding="utf-8")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main([
                "capture-insight",
                "--workspace", str(ws),
                "--insight", "Float division precision loss",
                "--context-files", "lib/math.py",
                "--format", "json",
            ])

        assert exit_code == 0
        output_json = json.loads(stdout.getvalue())
        assert output_json["insight"] == "Float division precision loss"

    def test_run_capture_insight_failure(self, tmp_path):
        """Failure inside capture_insight outputs error to stderr and returns 1."""
        from argparse import Namespace
        from soma_cli.cli import cmd_capture_insight

        args = Namespace(
            ws=None,
            workspace=str(tmp_path),
            _project_root=str(tmp_path),
            insight="",
            context_files=[],
            source_conversation=None,
            category=None,
            scaffold_wall=False,
            wall_id=None,
            json=False,
            format="text",
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = cmd_capture_insight(args)
        assert exit_code == 1
        assert "Error:" in stderr.getvalue()

