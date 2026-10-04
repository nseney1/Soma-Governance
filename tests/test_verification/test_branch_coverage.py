"""TDD tests for branch_coverage.py — AUDITED ground truth.

Audit findings applied:
- test_returns_tool_evidence: strengthened with verdict + target + empty lines
- test_dead_branch_detected: asserts specific uncovered line ranges
- test_reports_uncovered_lines: asserts exact line 3, not just >= 2
- test_full_coverage_passes: asserts empty lines list
"""
import json
import os
import sys
import textwrap

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from immune_system.verification import ToolEvidence


class TestBranchCoverageContract:
    """Behavioral contract for branch_coverage.check()."""

    def test_returns_tool_evidence(self, tmp_path):
        """check() must return passing ToolEvidence for fully covered code."""
        from immune_system.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def classify(x):
                if x > 0:
                    return "positive"
                else:
                    return "non-positive"
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import classify
            def test_positive():
                assert classify(5) == "positive"
            def test_negative():
                assert classify(-1) == "non-positive"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert isinstance(result, ToolEvidence)
        assert result.tool == "branch_coverage"
        assert "target.py" in result.target
        assert result.verdict is True
        assert result.lines == []

    def test_full_coverage_passes(self, tmp_path):
        """When all branches are covered, verdict=True and no uncovered lines."""
        from immune_system.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def classify(x):
                if x > 0:
                    return "positive"
                else:
                    return "non-positive"
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import classify
            def test_positive():
                assert classify(5) == "positive"
            def test_negative():
                assert classify(-1) == "non-positive"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert result.verdict is True
        assert result.lines == []

    def test_dead_branch_detected(self, tmp_path):
        """Uncovered branches must produce verdict=False with specific lines."""
        from immune_system.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def classify(x):
                if x > 0:
                    return "positive"
                elif x == 0:
                    return "zero"
                else:
                    return "negative"
        """))

        # Only tests positive — misses zero and negative branches
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import classify
            def test_positive():
                assert classify(5) == "positive"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert result.verdict is False
        # Lines 4-7 (elif/else branches) should be uncovered
        assert any(line in (4, 5, 6, 7) for line in result.lines), \
            f"Expected uncovered branch lines 4-7, got {result.lines}"
        # Line 3 (return "positive") was executed and must NOT be flagged
        assert 3 not in result.lines, \
            f"Covered line 3 was incorrectly flagged: {result.lines}"

    def test_reports_uncovered_lines(self, tmp_path):
        """Result must include the specific uncovered line number."""
        from immune_system.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def process(x):
                if x > 10:
                    return "big"
                return "small"
        """))

        # Only tests small path
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import process
            def test_small():
                assert process(5) == "small"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert result.verdict is False
        # Line 3 (return "big") should be uncovered
        assert 3 in result.lines, \
            f"Expected line 3 (return 'big') in uncovered lines, got {result.lines}"
        # Line 4 (return "small") was executed
        assert 4 not in result.lines, \
            f"Line 4 was executed and must not be in uncovered lines: {result.lines}"


class TestParseCoverageMissingBranches:
    """Fix 2.1a: _parse_coverage must merge missing_branches into results."""

    def test_parse_coverage_includes_missing_branches(self, tmp_path):
        """missing_branches entries should appear in the returned line list."""
        from immune_system.verification.branch_coverage import _parse_coverage

        # Build a mock coverage JSON with both missing_lines and missing_branches
        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                "/src/target.py": {
                    "missing_lines": [10, 15],
                    "missing_branches": [
                        [8, 12],   # branch from line 8 to 12
                        [14, 20],  # branch from line 14 to 20
                        [3, 15],   # to_line 15 already in missing_lines — no dup
                    ],
                }
            }
        }))

        result = _parse_coverage(str(report), "/src/target.py", "target.py")

        # Original missing_lines must be present
        assert 10 in result
        assert 15 in result
        # Branch targets must be merged in
        assert 12 in result, f"Branch target 12 missing from {result}"
        assert 20 in result, f"Branch target 20 missing from {result}"
        # No duplicates for line 15
        assert result.count(15) == 1, f"Duplicate line 15 in {result}"

    def test_parse_coverage_branches_only(self, tmp_path):
        """When missing_lines is empty, branches alone should populate result."""
        from immune_system.verification.branch_coverage import _parse_coverage

        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                "/src/foo.py": {
                    "missing_lines": [],
                    "missing_branches": [[5, 7]],
                }
            }
        }))

        result = _parse_coverage(str(report), "/src/foo.py", "foo.py")
        assert 7 in result
        assert len(result) == 1


class TestSubprocessTimeout:
    """Fix 2.1b: TimeoutExpired must be caught, not crash."""

    def test_subprocess_timeout_returns_false(self, monkeypatch):
        """_try_pytest_cov must return False on TimeoutExpired, not raise."""
        import subprocess as sp
        from immune_system.verification.branch_coverage import _try_pytest_cov

        def mock_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="pytest", timeout=120)

        monkeypatch.setattr(sp, "run", mock_run)

        result = _try_pytest_cov("test.py", "/src", "/tmp/report.json")
        assert result is False

    def test_coverage_module_timeout_returns_false(self, monkeypatch):
        """_try_coverage_module must return False on TimeoutExpired."""
        import subprocess as sp
        from immune_system.verification.branch_coverage import _try_coverage_module

        def mock_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="coverage", timeout=120)

        monkeypatch.setattr(sp, "run", mock_run)

        result = _try_coverage_module("test.py", "/src", "/tmp/report.json", "/tmp")
        assert result is False
