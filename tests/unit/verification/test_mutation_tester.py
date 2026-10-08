from pathlib import Path
"""TDD tests for mutation_tester.py — AUDITED ground truth.

Audit findings applied:
- test_returns_tool_evidence: strengthened with verdict + target assertions
- test_reports_survival_count: regex for numeric survived/total
- test_respects_max_mutations: was TAUTOLOGICAL, now asserts budget cap
"""
import os
import re
import sys
import textwrap

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from soma_core.verification import ToolEvidence


class TestMutationTesterContract:
    """Behavioral contract for mutation_tester.check()."""

    def test_returns_tool_evidence(self, tmp_path):
        """check() must return a passing ToolEvidence for a well-tested function."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def add(a, b):
                return a + b
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import add
            def test_add():
                assert add(2, 3) == 5
        """))

        result = mutation_tester.check(
            target_file=str(src),
            target_function="add",
            test_file=str(test),
        )
        assert isinstance(result, ToolEvidence)
        assert result.tool == "mutation_tester"
        assert "add" in result.target
        assert result.verdict is True
        assert result.lines == []  # No surviving mutations

    def test_catches_tautological_test(self, tmp_path):
        """A test that passes regardless of implementation should FAIL."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def compute(x):
                return x * 2
        """))

        # Tautological: doesn't check the return value
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import compute
            def test_compute():
                result = compute(5)
                assert isinstance(result, int)  # passes for ANY int return
        """))

        result = mutation_tester.check(
            target_file=str(src),
            target_function="compute",
            test_file=str(test),
        )
        assert result.verdict is False, \
            "Tautological test should be detected (mutations survive)"
        assert 2 in result.lines, \
            f"Surviving mutation should be on line 2 (return x * 2), got {result.lines}"

    def test_real_test_passes(self, tmp_path):
        """A test that validates behavior should PASS (no survivors)."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def multiply(a, b):
                return a * b
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import multiply
            def test_multiply_basic():
                assert multiply(3, 4) == 12
            def test_multiply_zero():
                assert multiply(0, 5) == 0
            def test_multiply_negative():
                assert multiply(-2, 3) == -6
        """))

        result = mutation_tester.check(
            target_file=str(src),
            target_function="multiply",
            test_file=str(test),
        )
        assert result.verdict is True, \
            f"Real tests should catch mutations, but got: {result.detail}"
        assert result.lines == [], \
            f"No mutations should survive, but got survivors at: {result.lines}"

    def test_reports_survival_count(self, tmp_path):
        """Result detail must include numeric survived vs total counts."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def negate(x):
                return -x
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import negate
            def test_negate():
                assert negate(5) == -5
        """))

        result = mutation_tester.check(
            target_file=str(src),
            target_function="negate",
            test_file=str(test),
        )
        # Detail must contain numeric counts like "0/3 survived" or "0 of 3"
        assert re.search(r"\d+\s*(?:/|\s+of\s+)\s*\d+", result.detail), \
            f"Detail must include survived/total counts, got: {result.detail}"

    def test_empty_function_passes(self, tmp_path):
        """A function with no mutable operations should pass trivially."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def noop():
                pass
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import noop
            def test_noop():
                assert noop() is None
        """))

        result = mutation_tester.check(
            target_file=str(src),
            target_function="noop",
            test_file=str(test),
        )
        assert result.verdict is True


class TestMutationTesterBudget:
    """Verify mutation budget controls."""

    def test_respects_max_mutations(self, tmp_path):
        """Must not generate more mutations than the budget allows."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def big_function(a, b, c, d):
                x = a + b
                y = c - d
                z = x * y
                w = z / max(a, 1)
                return x + y + z + w
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import big_function
            def test_basic():
                result = big_function(2, 3, 4, 1)
                assert isinstance(result, (int, float))
        """))

        result = mutation_tester.check(
            target_file=str(src),
            target_function="big_function",
            test_file=str(test),
            max_mutations=3,
        )
        assert isinstance(result, ToolEvidence)
        # Parse total mutations attempted from detail
        match = re.search(r"(\d+)\s*(?:/|\s+of\s+)\s*(\d+)", result.detail) or \
                re.search(r"(\d+)\s+mutation", result.detail)
        assert match, f"Could not parse mutation count from: {result.detail}"
        total = int(match.group(2)) if match.lastindex >= 2 else int(match.group(1))
        assert total <= 3, f"Expected <= 3 mutations attempted, got {total}"


class TestMutationTesterFailsClosed:
    """BUG-034: tests that cannot pass against the unmutated code used to
    count as killing every mutant, so check() reported verdict=True."""

    def _target(self, tmp_path):
        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def add(a, b):
                return a + b
        """))
        return src

    def test_unrunnable_test_file_fails_closed(self, tmp_path):
        from soma_core.verification import mutation_tester

        src = self._target(tmp_path)
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import add
            def test_add(:
                assert add(1, 2) == 3
        """))

        result = mutation_tester.check(str(src), "add", str(test))
        assert result.verdict is False
        assert "baseline" in result.detail.lower()
        assert result.lines == [-1]

    def test_baseline_assertion_failure_fails_closed(self, tmp_path):
        from soma_core.verification import mutation_tester

        src = self._target(tmp_path)
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import add
            def test_add():
                assert add(1, 2) == 4
        """))

        result = mutation_tester.check(str(src), "add", str(test))
        assert result.verdict is False
        assert "baseline" in result.detail.lower()


class TestMutationTesterAppliesEveryCollectedMutation:
    """BUG-039: comparison, boolean, statement-deletion and return-value
    mutations were counted but never applied, so a test that doesn't
    check them still reported verdict=True ("0/2 survived")."""

    def test_unchecked_comparison_survives(self, tmp_path):
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def eq(a, b):
                return a == b
        """))
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import eq
            def test_eq():
                eq(1, 2)
        """))

        result = mutation_tester.check(str(src), "eq", str(test))
        assert result.verdict is False, result.detail
        assert result.detail == "2/2 survived"

    def test_checked_boolean_logic_kills_mutants(self, tmp_path):
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def both(a, b):
                return a and b
        """))
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import both
            def test_both():
                assert both(True, False) is False
                assert both(True, True) is True
        """))

        result = mutation_tester.check(str(src), "both", str(test))
        assert result.verdict is True, result.detail
        assert result.detail == "0/2 survived"

    def test_docstring_and_return_none_are_not_mutated(self, tmp_path):
        """Deleting a docstring or turning `return None` into `return None`
        changes nothing, so no test could kill those mutants."""
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent('''\
            def add(a, b):
                """Add two numbers."""
                return a + b

            def nothing(x):
                return None
        '''))
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import add, nothing
            def test_add():
                assert add(1, 2) == 3
                assert add(2, 5) == 7
            def test_nothing():
                assert nothing(1) is None
        """))

        documented = mutation_tester.check(str(src), "add", str(test))
        assert documented.verdict is True, documented.detail
        assert documented.detail == "0/2 survived"
        returns_none = mutation_tester.check(str(src), "nothing", str(test))
        assert returns_none.verdict is True, returns_none.detail


class TestMutationTesterBoolAndTargetLines:
    """Tests for boolean constant mutation and target_lines scoping."""

    def test_bool_constant_mutated(self, tmp_path):
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def is_ready():
                return True
        """))
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import is_ready
            def test_ready():
                assert is_ready() is True
        """))

        result = mutation_tester.check(str(src), "is_ready", str(test))
        assert result.verdict is True
        assert "survived" in result.detail

    def test_target_lines_filtering(self, tmp_path):
        from soma_core.verification import mutation_tester

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def calc(x):
                a = x + 1
                b = a * 2
                return b
        """))
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import calc
            def test_calc():
                assert calc(3) == 8
        """))

        # Restrict mutation testing only to line 2 (a = x + 1)
        res_line2 = mutation_tester.check(str(src), "calc", str(test), target_lines={2})
        assert res_line2.verdict is True

        # Restrict mutation testing to a line with no mutations (e.g. line 1 def calc)
        res_empty = mutation_tester.check(str(src), "calc", str(test), target_lines={1})
        assert res_empty.verdict is True
        assert res_empty.detail == "No mutations on modified lines"

