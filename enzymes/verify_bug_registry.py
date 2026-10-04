#!/usr/bin/env python3
"""Verify Bug Registry — ensures every bug entry has valid data and a passing regression test.

Usage:
    python3 enzymes/verify_bug_registry.py [--workspace PATH]

Exit codes:
    0 = all bugs verified
    1 = verification failures found
"""
import json
import os
import subprocess
import sys


def load_registry(workspace: str) -> dict:
    """Load and parse BUG_REGISTRY.json."""
    path = os.path.join(workspace, 'docs', 'project', 'BUG_REGISTRY.json')
    if not os.path.exists(path):
        print(f"ERROR: Bug registry not found at {path}")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


VALID_STATUSES = ('open', 'fixed')
CORE_FIELDS = (
    'id', 'title', 'discovered_in', 'root_cause', 'severity', 'affected_files',
)
FIX_FIELDS = ('fixed_in', 'regression_test', 'changelog_ref')


def bug_status(bug: dict) -> str:
    # Entries predating the status field were all registered after their fix.
    return bug.get('status', 'fixed')


def verify_schema(registry: dict) -> list[str]:
    """Verify registry schema and required fields."""
    errors = []
    valid_categories = set(registry.get('root_cause_categories', {}).keys())
    valid_severities = set(registry.get('severity_levels', []))

    for bug in registry.get('bugs', []):
        bug_id = bug.get('id', '<unknown>')
        status = bug_status(bug)

        if status not in VALID_STATUSES:
            errors.append(
                f"{bug_id}: unknown status '{status}' "
                f"(valid: {', '.join(VALID_STATUSES)})"
            )

        # Open bugs are tracked before any fix exists; requiring fix fields
        # would force fabricated versions and tests.
        required_fields = CORE_FIELDS if status == 'open' else CORE_FIELDS + FIX_FIELDS
        for field in required_fields:
            if field not in bug or not bug[field]:
                errors.append(f"{bug_id}: missing required field '{field}'")

        if status == 'open':
            for field in FIX_FIELDS:
                if bug.get(field):
                    errors.append(
                        f"{bug_id}: status is 'open' but '{field}' is set; "
                        f"mark it 'fixed' or remove the field"
                    )

        # Root cause validation
        if bug.get('root_cause') and bug['root_cause'] not in valid_categories:
            errors.append(
                f"{bug_id}: unknown root_cause '{bug['root_cause']}' "
                f"(valid: {', '.join(sorted(valid_categories))})"
            )

        # Severity validation
        if bug.get('severity') and bug['severity'] not in valid_severities:
            errors.append(
                f"{bug_id}: unknown severity '{bug['severity']}' "
                f"(valid: {', '.join(sorted(valid_severities))})"
            )

    return errors


def _failed_node_ids(pytest_stdout: str) -> list[str]:
    """Node IDs from pytest's `FAILED <id> - ...` / `ERROR <id>` summary lines."""
    nodes = []
    for line in pytest_stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ('FAILED', 'ERROR'):
            nodes.append(parts[1])
    return nodes


def _node_matches(node: str, test_ref: str) -> bool:
    # A ref may name a whole parametrized test or a class; matching by name
    # substring blamed test_check for a test_check_more failure.
    if node == test_ref or node.startswith((test_ref + '[', test_ref + '::')):
        return True
    # A collection error is reported against the file alone.
    return '::' not in node and test_ref.split('::')[0] == node


def verify_regression_tests(registry: dict, workspace: str) -> list[str]:
    """Verify each bug's regression test exists and can be collected by pytest."""
    errors = []
    test_ids = []

    for bug in registry.get('bugs', []):
        if bug_status(bug) == 'open':
            continue
        bug_id = bug.get('id', '<unknown>')
        test_ref = bug.get('regression_test', '')
        if not test_ref:
            errors.append(f"{bug_id}: no regression_test specified")
            continue

        # Extract file path from pytest node ID (e.g., tests/foo.py::TestClass::test_method)
        test_file = test_ref.split('::')[0]
        full_path = os.path.join(workspace, test_file)
        if not os.path.exists(full_path):
            errors.append(f"{bug_id}: regression test file not found: {test_file}")
            continue

        test_ids.append((bug_id, test_ref))

    # Batch verify: run all test IDs to prove they pass.
    if test_ids:
        all_refs = [ref for _, ref in test_ids]
        # A fixed 30 s limit for the whole batch was nearly used up on Windows,
        # where tests that spawn Git Bash take seconds each. The budget
        # grows with the registry and still catches a hung test.
        budget = 60 + 5 * len(all_refs)
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', '-q', '-rfE'] + all_refs,
                capture_output=True, text=True, cwd=workspace, timeout=budget,
            )
            if result.returncode != 0:
                errors.append(f"Regression tests failed (exit code {result.returncode})")
                failed = _failed_node_ids(result.stdout)
                for bug_id, test_ref in test_ids:
                    if any(_node_matches(node, test_ref) for node in failed):
                        errors.append(f"{bug_id}: regression test failed: {test_ref}")
        except subprocess.TimeoutExpired:
            errors.append(f"Timeout running {len(all_refs)} regression tests (limit {budget} s)")
        except Exception as e:
            errors.append(f"Error running tests: {e}")

    return errors


def verify_unique_ids(registry: dict) -> list[str]:
    """Verify all bug IDs are unique."""
    errors = []
    seen = set()
    for bug in registry.get('bugs', []):
        bug_id = bug.get('id', '')
        if bug_id in seen:
            errors.append(f"Duplicate bug ID: {bug_id}")
        seen.add(bug_id)
    return errors


def main():
    # The report uses non-ASCII symbols; a cp1252 stdout raised
    # UnicodeEncodeError instead of listing the errors (BUG-012).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    workspace = '.'
    if '--workspace' in sys.argv:
        idx = sys.argv.index('--workspace')
        workspace = sys.argv[idx + 1]

    registry = load_registry(workspace)
    bugs = registry.get('bugs', [])

    print(f"Verifying {len(bugs)} bug entries...")

    all_errors = []
    all_errors.extend(verify_unique_ids(registry))
    all_errors.extend(verify_schema(registry))
    all_errors.extend(verify_regression_tests(registry, workspace))

    if all_errors:
        print(f"\n❌ {len(all_errors)} verification error(s):")
        for err in all_errors:
            print(f"  • {err}")
        sys.exit(1)

    # Summary
    categories = {}
    for bug in bugs:
        cat = bug.get('root_cause', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1

    open_count = sum(1 for bug in bugs if bug_status(bug) == 'open')
    print(f"\n=== All {len(bugs)} bugs verified ({open_count} open) ===")
    print(f"  Pattern distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count}")


if __name__ == '__main__':
    main()
