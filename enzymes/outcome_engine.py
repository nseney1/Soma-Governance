#!/usr/bin/env python3
"""Outcome Engine — Verifiable execution feedback for Soma cell fitness.

ACE-aligned reflector: captures REAL outcomes (test exit codes, build status,
git reverts) instead of proxy signals (file existence, commit messages).

Signal hierarchy (strongest → weakest):
  1. Test exit code (ground truth — did pytest/jest/go test PASS?)
  2. Build exit code (did `make build` or equivalent succeed?)
  3. Git reverts/force-pushes (verifiable failure signal)
  4. Rework detection (same file in consecutive commits)
  5. MCP-reported outcomes (agent self-report — weakest)

Reference: ACE (arXiv:2510.04618) — "ACE could adapt effectively without
labeled supervision and instead by leveraging natural execution feedback."
"""

import os
import sys
import subprocess
import json
import re
import glob
import fnmatch
import hashlib
import tempfile
import yaml
from datetime import datetime, timezone
from pathlib import Path
from soma_resolve import resolve_workspace

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from soma_sdk.cells import parse_cell_file




# ── Signal Capture: Verifiable Outcomes ──────────────────────────────

# Timeout for test/build commands (seconds). Don't hang the session.
VERIFY_TIMEOUT = int(os.environ.get('SOMA_VERIFY_TIMEOUT', '60'))


def _run_verify(cmd, cwd, timeout=None):
    """Run a verification command, return (exit_code, stdout_snippet).

    Returns None if the command doesn't exist or times out.
    """
    if timeout is None:
        timeout = VERIFY_TIMEOUT
    try:
        result = subprocess.run(
            cmd, cwd=cwd, shell=True, timeout=timeout,
            capture_output=True, text=True
        )
        # Capture last 10 lines of output for debugging
        stdout_tail = '\n'.join(result.stdout.strip().split('\n')[-10:])
        stderr_tail = '\n'.join(result.stderr.strip().split('\n')[-5:])
        return {
            'exit_code': result.returncode,
            'passed': result.returncode == 0,
            'stdout_tail': stdout_tail[:500],
            'stderr_tail': stderr_tail[:300]
        }
    except subprocess.TimeoutExpired:
        return {'exit_code': -1, 'passed': None, 'error': 'timeout'}
    except FileNotFoundError:
        return None
    except Exception as e:
        return {'exit_code': -1, 'passed': None, 'error': str(e)[:200]}


def detect_test_runner(workspace):
    """Detect which test framework this project uses.

    Returns (command, framework_name) or (None, None).
    Verifies the runner is actually installed before returning.
    """
    checks = [
        # Python — verify pytest is importable
        ('pyproject.toml', 'pytest',
         'python3 -m pytest --tb=short -q --no-header 2>&1',
         'python3 -c "import pytest" 2>/dev/null'),
        ('setup.cfg', 'pytest',
         'python3 -m pytest --tb=short -q --no-header 2>&1',
         'python3 -c "import pytest" 2>/dev/null'),
        ('pytest.ini', 'pytest',
         'python3 -m pytest --tb=short -q --no-header 2>&1',
         'python3 -c "import pytest" 2>/dev/null'),

        # JavaScript/TypeScript — verify jest/vitest exists
        ('jest.config.js', 'jest',
         'npx jest --silent --no-coverage 2>&1',
         'npx jest --version 2>/dev/null'),
        ('jest.config.ts', 'jest',
         'npx jest --silent --no-coverage 2>&1',
         'npx jest --version 2>/dev/null'),
        ('vitest.config.ts', 'vitest',
         'npx vitest run --reporter=dot 2>&1',
         'npx vitest --version 2>/dev/null'),
        ('package.json', 'npm test',
         'npm test 2>&1',
         None),  # package.json always valid if it has a test script

        # Go
        ('go.mod', 'go test',
         'go test ./... -count=1 -short 2>&1',
         'go version 2>/dev/null'),

        # Rust
        ('Cargo.toml', 'cargo test',
         'cargo test --quiet 2>&1',
         'cargo --version 2>/dev/null'),

        # Generic Makefile test target
        ('Makefile', 'make test',
         'make test 2>&1',
         None),
    ]

    for entry in checks:
        marker_file, framework, cmd, verify_cmd = entry[0], entry[1], entry[2], entry[3]
        if not os.path.isfile(os.path.join(workspace, marker_file)):
            continue

        # For package.json, check if there's a "test" script
        if framework == 'npm test':
            try:
                with open(os.path.join(workspace, marker_file), encoding='utf-8') as f:
                    pkg = json.loads(f.read())
                if 'test' not in pkg.get('scripts', {}):
                    continue
                # Skip if test script is the default placeholder
                test_script = pkg['scripts']['test']
                if 'no test specified' in test_script:
                    continue
            except Exception:
                continue

        # For Makefile, verify 'test' target exists
        if framework == 'make test':
            try:
                targets = subprocess.check_output(
                    'make -qp 2>/dev/null | grep -E "^test:" || true',
                    shell=True, cwd=workspace, text=True
                )
                if 'test:' not in targets:
                    continue
            except Exception:
                continue

        # Verify the runner is actually installed
        if verify_cmd:
            try:
                result = subprocess.run(
                    verify_cmd, shell=True, cwd=workspace,
                    capture_output=True, timeout=10
                )
                if result.returncode != 0:
                    continue  # Runner not installed — skip
            except Exception:
                continue

        return cmd, framework

    return None, None


def capture_test_outcome(workspace):
    """Run the actual test suite and capture the exit code.

    This is the ACE reflector's ground truth signal.
    Returns:
        {
            'verified': True/False,  # Did we actually run tests?
            'passed': True/False/None,
            'framework': str,
            'exit_code': int,
            'detail': str
        }
    """
    # Check if verification is disabled
    if os.environ.get('SOMA_SKIP_VERIFY', '').lower() in ('1', 'true', 'yes'):
        return {'verified': False, 'passed': None, 'reason': 'SOMA_SKIP_VERIFY set'}

    cmd, framework = detect_test_runner(workspace)
    if not cmd:
        return {'verified': False, 'passed': None, 'reason': 'no test runner detected'}

    result = _run_verify(cmd, workspace)
    if result is None:
        return {'verified': False, 'passed': None, 'reason': f'{framework} not installed'}

    return {
        'verified': True,
        'passed': result['passed'],
        'framework': framework,
        'exit_code': result['exit_code'],
        'detail': result.get('stdout_tail', '')[:200],
        'error': result.get('error', result.get('stderr_tail', ''))[:200]
    }


def capture_build_outcome(workspace):
    """Try to build the project if a build system is detected."""
    # Only try if there's a Makefile with a 'build' target
    if not os.path.isfile(os.path.join(workspace, 'Makefile')):
        return {'verified': False, 'passed': None}

    try:
        targets = subprocess.check_output(
            'make -qp 2>/dev/null | grep -E "^build:" || true',
            shell=True, cwd=workspace, text=True
        )
        if 'build:' not in targets:
            return {'verified': False, 'passed': None}
    except Exception:
        return {'verified': False, 'passed': None}

    result = _run_verify('make build 2>&1', workspace, timeout=120)
    if result is None:
        return {'verified': False, 'passed': None}

    return {
        'verified': True,
        'passed': result['passed'],
        'exit_code': result['exit_code']
    }


def capture_git_signals(workspace):
    """Check for reverts and force-pushes — verifiable failure signals."""
    signals = {
        'reverts': 0,
        'fixups': 0,
        'rework_files': [],
        'force_pushes': 0,
        'verified': True  # Git signals are always verifiable
    }

    try:
        # Check last 5 commits for reverts
        log_out = subprocess.check_output(
            ['git', 'log', '--oneline', '-5'],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        ).lower()
        signals['reverts'] = log_out.count('revert')
        signals['fixups'] = log_out.count('fixup') + log_out.count('wip')
    except Exception:
        signals['verified'] = False

    try:
        # Check reflog for force-pushes
        reflog = subprocess.check_output(
            ['git', 'reflog', '-5', '--format=%gs'],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        ).lower()
        signals['force_pushes'] = reflog.count('push (force')
    except Exception:
        pass

    try:
        # Rework detection: files touched in 2+ of the last 5 commits
        log_out = subprocess.check_output(
            ['git', 'log', '--name-only', '--format=', '-5'],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        from collections import Counter
        files = [f for f in log_out.splitlines() if f.strip()]
        counts = Counter(files)
        signals['rework_files'] = [f for f, c in counts.items() if c > 1]
    except Exception:
        pass

    return signals


def capture_mcp_outcomes(workspace):
    """Read any soma_report_outcome calls from this session."""
    signals_file = os.path.join(workspace, '.soma', 'evidence', 'signals.jsonl')
    outcomes = []
    if not os.path.isfile(signals_file):
        return outcomes
    try:
        with open(signals_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    # Filter for outcomes (either legacy outcome field or new signal field)
                    if record.get('outcome') or record.get('signal') in ('tp', 'fp', 'success', 'failure'):
                        # Map signal back to outcome for backward compatibility in compute_fitness_signals
                        if 'signal' in record and 'outcome' not in record:
                            record['outcome'] = record['signal']
                        outcomes.append(record)
    except Exception:
        pass
    return outcomes


def _insight_cursor_path(workspace):
    return os.path.join(workspace, '.soma', 'insight_cursor')


def _read_insight_cursor(workspace):
    """Return the committed byte offset into human_insights.jsonl (0 if none/invalid)."""
    try:
        with open(_insight_cursor_path(workspace), 'r', encoding='utf-8') as cf:
            value = int(cf.read().strip())
    except (OSError, ValueError):
        return 0
    return value if value >= 0 else 0


def commit_insight_cursor(workspace, offset):
    """Atomically persist the insight cursor (temp file + os.replace).

    Returns True on success (or when the cursor is already at ``offset``).
    """
    if offset is None:
        return True
    cursor_file = _insight_cursor_path(workspace)
    if os.path.isfile(cursor_file) and _read_insight_cursor(workspace) == offset:
        return True
    cursor_dir = os.path.dirname(cursor_file)
    tmp_path = None
    try:
        os.makedirs(cursor_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cursor_dir, prefix='.insight_cursor.', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as cf:
            cf.write(str(int(offset)))
            cf.flush()
            os.fsync(cf.fileno())
        os.replace(tmp_path, cursor_file)
        return True
    except (OSError, ValueError, TypeError) as e:
        print(f"    ! failed to commit insight cursor: {e}", file=sys.stderr)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def capture_human_insight_signals(workspace):
    """Backward-compatible wrapper: read NEW insights and commit the cursor.

    Prefer read_human_insight_signals() + commit_insight_cursor() so the
    cursor only advances after the derived evidence is durably persisted.
    """
    signals, new_offset = read_human_insight_signals(workspace)
    commit_insight_cursor(workspace, new_offset)
    return signals


def read_human_insight_signals(workspace):
    """Read NEW human insight annotations and produce fitness signals.

    Never writes the cursor. Uses the committed byte-offset cursor
    (.soma/insight_cursor) to only process insights added since the last
    commit, and only advances over complete newline-terminated lines: a
    trailing partial line (writer mid-append) is re-read next time.

    Returns ``(signals, new_offset)``. signals are compatible with update_cell_fitness() schema:
      - _path: absolute path to cell file
      - signal: float (positive = boost)
      - cell: cell name
      - reasons: list of explanation strings
      - verified: True (human ground truth)
      - signal_type: 'human_insight' or 'blind_spot'
      - weight: configurable (default 0.5)
      - files: context files from the insight

    Blind spot signals (uncovered insights) have _path=None and are
    excluded from update_cell_fitness but included for reporting.
    """
    insights_file = os.path.join(workspace, '.soma', 'human_insights.jsonl')
    cursor_offset = _read_insight_cursor(workspace)
    if not os.path.isfile(insights_file):
        return [], cursor_offset

    file_size = os.path.getsize(insights_file)
    if cursor_offset > file_size:
        cursor_offset = 0  # file was truncated/rotated: start over

    # Read configurable weight
    weight = 0.5
    config_path = os.path.join(workspace, '.soma', 'config.yaml')
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            weight = float(config.get('insight_signal_weight', 0.5))
        except Exception:
            pass

    # Build cell name → file path index
    cell_paths = {}
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if os.path.isdir(cells_dir):
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            name = os.path.splitext(os.path.basename(cell_file))[0]
            cell_paths[name] = cell_file

    try:
        with open(insights_file, 'rb') as f:
            f.seek(cursor_offset)
            data = f.read()
    except OSError:
        return [], cursor_offset

    # Only consume complete, newline-terminated lines.
    last_newline = data.rfind(b'\n')
    if last_newline == -1:
        return [], cursor_offset
    complete = data[:last_newline + 1]
    new_offset = cursor_offset + len(complete)

    signals = []
    line_offset = cursor_offset
    for raw_line in complete.split(b'\n'):
        this_offset = line_offset
        line_offset += len(raw_line) + 1
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue  # complete but malformed: skip permanently
        if not isinstance(record, dict):
            continue
        # Stable identity for this insight line: retries after a failed
        # persist append the same evidence event instead of a duplicate.
        insight_id = f"{this_offset}:{hashlib.sha256(raw_line).hexdigest()}"

        if record.get('was_covered'):
            # Covered insight — boost matching cells
            for cell_name in record.get('covering_cells', []):
                cell_path = cell_paths.get(cell_name)
                if cell_path:
                    signals.append({
                        'cell': cell_name,
                        '_path': cell_path,
                        'signal': weight,
                        'reasons': [f"human insight: {record.get('insight', '')[:80]}"],
                        'verified': True,
                        'signal_type': 'human_insight',
                        'insight_id': insight_id,
                        'weight': weight,
                        'files': record.get('context_files', []),
                    })
        else:
            # Uncovered insight — governance blind spot
            signals.append({
                'cell': None,
                '_path': None,
                'signal': 0.0,
                'reasons': [f"blind spot: {record.get('insight', '')[:80]}"],
                'verified': True,
                'signal_type': 'blind_spot',
                'weight': weight,
                'files': record.get('context_files', []),
            })

    return signals, new_offset

# ── Frontmatter Parser ────────────────────────────────────────────────

def _parse_frontmatter(content, filepath=None):
    """Parse YAML frontmatter robustly using parse_cell_file.

    When *filepath* is provided, delegates to the canonical parser.
    Falls back to inline parsing when only raw *content* is available.
    """
    if filepath is not None:
        try:
            fm, _body = parse_cell_file(filepath)
            return fm
        except Exception:
            return {}
    # Fallback: parse from raw content string
    if not content.startswith('---'):
        return {}
    end = content.find('---', 3)
    if end == -1:
        return {}
    fm_text = content[3:end].strip()
    try:
        return yaml.safe_load(fm_text) or {}
    except Exception:
        return {}


def _as_int(value, default=0):
    """Coerce a frontmatter counter to int; hand-edited cells carry strings."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ── Cell Matching ────────────────────────────────────────────────────

def _get_changed_files(workspace):
    """Get changed files using git."""
    files = set()
    for cmd in ['git diff --name-only', 'git diff --name-only HEAD~5 HEAD']:
        try:
            out = subprocess.check_output(
                cmd, shell=True, cwd=workspace, text=True,
                stderr=subprocess.DEVNULL
            )
            files.update(f for f in out.splitlines() if f.strip())
        except Exception:
            pass
    return list(files)


def match_cells_to_changes(workspace, changed_files):
    """Match cells to changed files using target_paths."""
    triggered = []
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if not os.path.isdir(cells_dir):
        return triggered

    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md':
            continue
        try:
            fm = _parse_frontmatter(None, filepath=cell_file)
            target_paths = fm.get('target_paths', [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]

            matched = False
            for fpath in changed_files:
                for tp in target_paths:
                    if fnmatch.fnmatch(fpath, tp) or fnmatch.fnmatch(os.path.basename(fpath), tp):
                        matched = True
                        break
                if matched:
                    break

            if matched:
                fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
                fm['_path'] = cell_file
                triggered.append(fm)
        except Exception:
            pass
    return triggered


# ── Fitness Signal Computation (ACE Reflector) ───────────────────────

def to_fraction(credit):
    """Convert credit float to a string Fraction (e.g., '1/3') for deterministic storage."""
    from fractions import Fraction
    if isinstance(credit, str) and '/' in credit:
        return credit # Already a fraction
    credit = max(0.0, min(1.0, float(credit)))
    f = Fraction(credit).limit_denominator(1000)
    return f"{f.numerator}/{f.denominator}"



def compute_credit_weights(triggered_cells, changed_files):
    """Compute per-cell credit weights using per-file scope narrowing.

    For each changed file, only cells whose target_paths match that file
    share credit. Credit per file sums to exactly 1.0 (conservation).
    A cell's total credit is the sum across all files it matches.

    Returns:
        dict: {cell_name: credit_weight} where credit_weight is a float.
    """
    if not changed_files or not triggered_cells:
        return {c.get('_name', c.get('id', '')): 1.0 for c in triggered_cells}

    # Build file → matching cells index
    file_to_cells = {}  # file_path → [cell_name, ...]
    for fpath in changed_files:
        matching = []
        for cell in triggered_cells:
            cell_name = cell.get('_name', cell.get('id', ''))
            target_paths = cell.get('target_paths', [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]
            for tp in target_paths:
                if fnmatch.fnmatch(fpath, tp) or fnmatch.fnmatch(os.path.basename(fpath), tp):
                    matching.append(cell_name)
                    break
        if matching:
            file_to_cells[fpath] = matching

    # Sum credit per cell across all files
    credit = {c.get('_name', c.get('id', '')): 0.0 for c in triggered_cells}
    for fpath, cell_names in file_to_cells.items():
        per_cell = 1.0 / len(cell_names)
        for cn in cell_names:
            credit[cn] += per_cell

    # Cells that matched no specific files get 0 credit
    # (they were triggered by match_cells_to_changes but don't match any
    # individual changed file — shouldn't happen but defensive)
    return credit

def compute_fitness_signals(triggered_cells, outcomes, changed_files=None):
    """ACE-aligned reflector: score cells based on VERIFIABLE outcomes.

    Signal weights:
      Test exit code:   ±1.0 (ground truth — strongest signal)
      Build exit code:  ±0.7 (strong signal)
      Git reverts:      -1.0 (verifiable failure)
      Rework detection: -0.3 (weak but verifiable)
      MCP self-report:  ±0.2 (weakest — agent grading itself)

    Credit assignment (Phase 3.1):
      When multiple cells match the same changed file, each cell's signal
      is weighted by its per-file credit (1/N where N = matching cells).
      This prevents double-counting: if 3 cells match src/foo.py and tests
      pass, each gets ~1/3 credit instead of full credit.

    A cell gets NO signal (0.0) if we can't verify the outcome.
    This is intentional: uncertain signals are worse than no signal.
    """
    credit_weights = compute_credit_weights(triggered_cells, changed_files or [])
    results = []
    test_outcome = outcomes.get('tests', {})
    build_outcome = outcomes.get('build', {})
    git = outcomes.get('git', {})
    mcp = outcomes.get('mcp', [])

    for cell in triggered_cells:
        signal = 0.0
        reasons = []

        # 1. Test exit code — GROUND TRUTH
        if test_outcome.get('verified') and test_outcome.get('passed') is not None:
            if test_outcome['passed']:
                signal += 1.0
                reasons.append(f"tests passed ({test_outcome.get('framework', '?')})")
            else:
                signal -= 1.0
                reasons.append(f"tests FAILED ({test_outcome.get('framework', '?')})")

        # 2. Build exit code — STRONG SIGNAL
        elif build_outcome.get('verified') and build_outcome.get('passed') is not None:
            if build_outcome['passed']:
                signal += 0.7
                reasons.append("build passed")
            else:
                signal -= 0.7
                reasons.append("build FAILED")

        # 3. Git reverts — VERIFIABLE FAILURE
        if git.get('reverts', 0) > 0:
            signal -= 1.0
            reasons.append(f"{git['reverts']} revert(s) detected")

        # 4. Rework on cell's target files — WEAK BUT VERIFIABLE
        rework_files = git.get('rework_files', [])
        cell_targets = cell.get('target_paths', [])
        if isinstance(cell_targets, str):
            cell_targets = [cell_targets]

        rework_hit = False
        for rf in rework_files:
            for tp in cell_targets:
                if fnmatch.fnmatch(rf, tp):
                    rework_hit = True
                    break
            if rework_hit:
                break
        if rework_hit:
            signal -= 0.3
            reasons.append("rework detected on target files")

        # 5. MCP self-report — WEAKEST (agent grading itself)
        for mcp_entry in mcp:
            # Support both schemas: {cells_used: [list]} and {cell_id: str}
            cells_used = mcp_entry.get('cells_used', [])
            cell_id = mcp_entry.get('cell_id', '')
            if cell['_name'] in cells_used or cell['_name'] == cell_id:
                outcome = mcp_entry.get('outcome', '')
                if outcome == 'success':
                    # OVERCONFIDENCE PENALTY
                    if test_outcome.get('verified') and test_outcome.get('passed') is False:
                        signal -= 2.0
                        reasons.append("agent claimed success but tests FAILED (overconfidence penalty)")
                    elif not test_outcome.get('verified') and not build_outcome.get('verified') and git.get('reverts', 0) == 0:
                        signal -= 1.0
                        reasons.append("agent claimed success with zero verifiable evidence (overconfidence penalty)")
                    else:
                        signal += 0.2
                        reasons.append("agent reported success")
                elif outcome == 'failure':
                    signal -= 0.2
                    reasons.append("agent reported failure")

        # Clamp to [-2, 2] range
        signal = max(-2.0, min(2.0, signal))

        results.append({
            'cell': cell['_name'],
            '_path': cell['_path'],
            'signal': round(signal, 2),
            'reasons': reasons,
            'verified': test_outcome.get('verified', False) or build_outcome.get('verified', False),
            'credit_weight': credit_weights.get(cell['_name'], 1.0),
            'signal_method': 'credit_weighted',
        })

    return results


# ── Cell Fitness Update ──────────────────────────────────────────────

def update_cell_fitness(workspace, fitness_signals):
    """Update cell frontmatter with fitness signals using yaml."""
    for sig in fitness_signals:
        fpath = sig['_path']
        signal = sig['signal']
        try:
            try:
                fm, _body = parse_cell_file(fpath)
            except Exception:
                continue

            # Re-read raw content for the write path below
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            end = content.find('---', 3)
            if end == -1: continue

            # Normalize fitness to a dict.
            #
            # `score` is a 0..1 ratio everywhere else in the system
            # (cell_fitness.py computes tp/triggers; jit_engine.get_fitness_score
            # multiplies it by impact_weight). Seeding it with 100 made every cell
            # this engine touched outrank every other cell forever, so an unknown
            # score is None — meaning "not yet measured".
            fitness = fm.get('fitness')
            if fitness is None:
                fitness = {'score': None, 'impact_weight': 1.0}
            elif isinstance(fitness, bool):
                fitness = {'score': None, 'impact_weight': 1.0}
            elif isinstance(fitness, (int, float)):
                fitness = {'score': float(fitness), 'impact_weight': 1.0}
            elif isinstance(fitness, str):
                try:
                    fitness = {'score': float(fitness), 'impact_weight': 1.0}
                except ValueError:
                    fitness = {'score': None, 'impact_weight': 1.0}
            elif not isinstance(fitness, dict):
                fitness = {'score': None, 'impact_weight': 1.0}

            # Counters MUST live inside the nested `fitness` mapping: that is
            # where cell_fitness.py, cell_promote.py and jit_engine.py read them
            # from. Writing them at frontmatter top level made every outcome
            # signal invisible (triggers stayed 0 -> score None -> status NEW).
            fitness['triggers'] = _as_int(fitness.get('triggers', 0)) + 1
            fitness.setdefault('true_positives', 0)
            fitness.setdefault('false_positives', 0)
            # Preserve fractional exactness while ensuring numeric types in frontmatter
            if signal > 0:
                credit_weight = sig.get('credit_weight', 1.0)
                from fractions import Fraction
                raw_tp = str(fitness['true_positives']).strip()
                if '/' in raw_tp:
                    current = Fraction(raw_tp)
                else:
                    try:
                        current = Fraction(raw_tp)
                    except Exception:
                        current = Fraction(0)
                new_val = current + Fraction(to_fraction(credit_weight))
                r = round(float(new_val), 4)
                fitness['true_positives'] = int(r) if r.is_integer() else r
            elif signal < 0:
                credit_weight = sig.get('credit_weight', 1.0)
                from fractions import Fraction
                raw_fp = str(fitness['false_positives']).strip()
                if '/' in raw_fp:
                    current = Fraction(raw_fp)
                else:
                    try:
                        current = Fraction(raw_fp)
                    except Exception:
                        current = Fraction(0)
                new_val = current + Fraction(to_fraction(credit_weight))
                r = round(float(new_val), 4)
                fitness['false_positives'] = int(r) if r.is_integer() else r

            fitness['last_trigger_date'] = datetime.now(timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%SZ'
            )

            fm['fitness'] = fitness

            new_fm = yaml.dump(fm, sort_keys=False, default_flow_style=False,
                               allow_unicode=True)
            new_content = f"---\n{new_fm}---\n{content[end+3:].lstrip()}"

            tmp_fpath = f"{fpath}.tmp.{os.getpid()}"
            with open(tmp_fpath, 'w', encoding='utf-8') as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_fpath, fpath)
        except Exception as e:  # noqa: BLE001 - must not crash the session
            # Never crash the session, but never lose the signal silently either.
            print(f"    ! failed to update fitness for {fpath}: {e}", file=sys.stderr)


INSIGHT_PRINCIPAL = 'outcome_engine'
INSIGHT_SCOPE = 'human_insight'


def append_fitness_log(workspace, fitness_signals, outcomes, expected_generation=None,
                       idempotency_prefix=None):
    """Atomically append one outcome-engine batch to canonical evidence.

    Human insights retain their stable ``insight_id`` identities. Ordinary
    session signals share one per-run idempotency prefix; ``append_signals``
    adds cell identity when deriving each event id.
    """
    if not fitness_signals:
        return True
    try:
        from soma_sdk.telemetry import append_signals
    except ImportError:
        return False

    if idempotency_prefix is None:
        # Compatibility for direct callers; production main supplies this once
        # per run before constructing the batch.
        import secrets
        idempotency_prefix = secrets.token_hex(16)

    events = []
    for sig in fitness_signals:
        signal_val = sig.get('signal', 0)
        if signal_val > 0:
            signal_type = 'tp'
        elif signal_val < 0:
            signal_type = 'fp'
        else:
            signal_type = 'trigger'

        metadata = {
            'raw_signal': sig.get('signal'),
            'verified': sig.get('verified', False),
            'credit_weight': sig.get('credit_weight', 1.0),
            'signal_method': sig.get('signal_method', 'legacy'),
            'reasons': sig.get('reasons', []),
            'outcomes': {
                'tests': {
                    'verified': outcomes.get('tests', {}).get('verified', False),
                    'passed': outcomes.get('tests', {}).get('passed'),
                    'framework': outcomes.get('tests', {}).get('framework'),
                },
                'build': {
                    'verified': outcomes.get('build', {}).get('verified', False),
                    'passed': outcomes.get('build', {}).get('passed'),
                },
                'git': {
                    'reverts': outcomes.get('git', {}).get('reverts', 0),
                    'rework_count': len(outcomes.get('git', {}).get('rework_files', [])),
                },
            },
        }

        insight_id = sig.get('insight_id')
        if insight_id:
            metadata['insight_id'] = insight_id
            principal = INSIGHT_PRINCIPAL
            scope = INSIGHT_SCOPE
            key = insight_id
        else:
            principal = 'outcome_engine'
            scope = 'run'
            key = idempotency_prefix

        events.append({
            'cell_name': sig['cell'],
            'signal_type': signal_type,
            'source': 'session',
            'metadata': metadata,
            'principal': principal,
            'idempotency_scope': scope,
            'idempotency_key': key,
        })

    try:
        append_signals(
            workspace, events, expected_generation=expected_generation)
    except Exception as exc:  # noqa: BLE001 - must not crash the session
        print(f"    ! failed to log fitness signal batch: {exc}", file=sys.stderr)
        return False
    return True


# ── Main ─────────────────────────────────────────────────────────────

def main():
    workspace = resolve_workspace()
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if not os.path.isdir(cells_dir):
        return  # Graceful no-op

    print("  Running outcome engine (ACE reflector)...")

    # Epoch generation this run observes; evidence appends are fenced on it.
    try:
        from soma_sdk.telemetry import read_generation
        generation = read_generation(workspace)
    except ImportError:
        generation = None

    # 1. Capture verifiable outcomes
    outcomes = {}

    # Ground truth: run the actual test suite
    print("    Detecting test runner...", end=' ')
    outcomes['tests'] = capture_test_outcome(workspace)
    test_result = outcomes['tests']
    if test_result.get('verified'):
        status = '✅ PASSED' if test_result['passed'] else '❌ FAILED'
        print(f"{test_result.get('framework', '?')} → {status}")
    else:
        print(f"skipped ({test_result.get('reason', 'unknown')})")

    # Build signal
    outcomes['build'] = capture_build_outcome(workspace)

    # Git signals (always verifiable)
    outcomes['git'] = capture_git_signals(workspace)

    # MCP self-reports (weakest signal)
    mcp = capture_mcp_outcomes(workspace)
    if mcp:
        outcomes['mcp'] = mcp

    # Human insight signals (verified ground truth from user annotations).
    # Read only — the cursor is committed after the evidence is persisted.
    insight_signals, insight_offset = read_human_insight_signals(workspace)
    blind_spots = [s for s in insight_signals if s.get('signal_type') == 'blind_spot']
    cell_boosts = [s for s in insight_signals if s.get('_path') is not None]

    if blind_spots:
        print(f"    {len(blind_spots)} governance blind spot(s) detected from human insights")

    # 2. Match cells to changed files
    changed_files = _get_changed_files(workspace)
    triggered = match_cells_to_changes(workspace, changed_files)

    if not triggered and not cell_boosts:
        print("    No cells matched changed files.")
        # No insight-derived evidence to persist (blind spots are report-only).
        commit_insight_cursor(workspace, insight_offset)
        return

    # 3. Compute fitness signals (ACE reflector step)
    signals = compute_fitness_signals(triggered, outcomes, changed_files=changed_files) if triggered else []

    # Merge human insight signals, deduplicating cells already scored
    existing_paths = {s['_path'] for s in signals if '_path' in s}
    for boost in cell_boosts:
        if boost['_path'] not in existing_paths:
            signals.append(boost)
            existing_paths.add(boost['_path'])

    # 4. Evidence first, then the cursor, then derived state. signals.jsonl is
    # canonical and insight events are idempotent, so a failed run retries
    # without duplicating evidence; frontmatter is only touched after the
    # cursor commits, so a retry can never apply an insight boost twice (a
    # crash right after the commit can at worst miss one frontmatter update,
    # which `soma sync` rebuilds from the ledger). A migration since this run
    # started fails the appends (stale generation) and the run retries later.
    if signals:
        import secrets
        run_idempotency_prefix = secrets.token_hex(16)
        if append_fitness_log(
                workspace, signals, outcomes,
                expected_generation=generation,
                idempotency_prefix=run_idempotency_prefix):
            commit_insight_cursor(workspace, insight_offset)
            update_cell_fitness(workspace, signals)
        else:
            print("    ! evidence log incomplete; cells and insight cursor left unchanged "
                  "(will retry)", file=sys.stderr)
    else:
        commit_insight_cursor(workspace, insight_offset)

    # 5. Print summary
    verified_count = sum(1 for s in signals if s.get('verified'))
    print(f"    {len(signals)} cells evaluated ({verified_count} with verified outcomes)")
    for s in signals:
        indicator = '↑' if s['signal'] > 0 else '↓' if s['signal'] < 0 else '→'
        v = '✓' if s.get('verified') else '?'
        reasons_str = ', '.join(s.get('reasons', [])) or 'no signal'
        print(f"      {indicator} [{v}] {s['cell']}: {s['signal']:+.1f} ({reasons_str})")


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
