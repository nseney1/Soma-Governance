"""Cell data structures and utilities."""
from __future__ import annotations
from datetime import datetime, timezone, date
import math
import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Optional, Tuple, Union

import yaml

from soma_sdk.errors import CellParseError, CellNotFoundError, CellPathTraversalError
from soma_sdk.scoring import bayesian_posterior, laplace_score


@dataclass
class CellFitness:
    """Fitness metrics for a governance cell."""
    triggers: int = 0
    true_positives: Union[int, float] = 0
    false_positives: Union[int, float] = 0
    score: Optional[float] = None
    stress_survived: int = 0

    def __post_init__(self):
        self.triggers = int(self._coerce_num(self.triggers, default=0))
        self.true_positives = self._coerce_num(self.true_positives, default=0)
        self.false_positives = self._coerce_num(self.false_positives, default=0)
        if self.score is not None:
            self.score = self._coerce_num(self.score, default=None)

    @staticmethod
    def _coerce_num(val, default=0):
        if val is None or isinstance(val, bool):
            return default
        if isinstance(val, (int, float)):
            if not math.isfinite(val):
                return default
            val = max(0, val)
            return int(val) if isinstance(val, float) and val.is_integer() else val
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return default
            if '/' in val:
                try:
                    f = Fraction(val)
                    flt = float(f)
                    if not math.isfinite(flt):
                        return default
                    flt = max(0.0, flt)
                    return int(flt) if flt.is_integer() else round(flt, 4)
                except Exception:
                    return default
            try:
                flt = float(val)
                if not math.isfinite(flt):
                    return default
                flt = max(0.0, flt)
                return int(flt) if flt.is_integer() else round(flt, 4)
            except Exception:
                return default
        return default
    
    @property
    def raw_score(self) -> float | None:
        if self.triggers == 0:
            return None
        return self.true_positives / self.triggers
    
    @property
    def snr_db(self) -> float | None:
        """Signal-to-noise ratio in decibels."""
        tp, fp = self.true_positives, self.false_positives
        if tp > 0 and fp > 0:
            return round(10 * math.log10(tp / fp), 1)
        elif tp > 0:
            return None  # JSON-safe encoding of infinite SNR (RFC 8259)
        return 0.0
    
    def bayesian(self, confidence: float = 0.90) -> dict[str, float | str]:
        """Wilson-bounded posterior with Jeffrey's prior.

        Delegates to soma_sdk.scoring.bayesian_posterior.
        """
        return bayesian_posterior(
            tp=self.true_positives,
            fp=self.false_positives,
            confidence=confidence,
        )


@dataclass
class Cell:
    """A Soma immune cell."""
    name: str
    type: str  # wall | vacuole | membrane | chloroplast | plasmodesmata
    hypothesis: str = ''
    prediction: str = ''
    falsification: str = ''
    target_paths: list = field(default_factory=list)
    minimum_mode: str = 'breeze'
    tags: list = field(default_factory=list)
    fitness: CellFitness = field(default_factory=CellFitness)
    
    @property
    def is_wall(self) -> bool:
        return self.type == 'wall'
    
    @property
    def is_extinct(self) -> bool:
        if self.fitness.triggers == 0:
            return False
        score = laplace_score(self.fitness.true_positives, self.fitness.triggers)
        return score <= 0.15
    
    @property
    def is_promotable(self) -> bool:
        if self.fitness.triggers == 0:
            return False
        score = laplace_score(self.fitness.true_positives, self.fitness.triggers)
        return score > 0.85 and self.fitness.triggers >= 20

    def is_promotable_with_age(self, min_age_days: int = 0) -> bool:
        if not self.is_promotable:
            return False
        if min_age_days > 0 and getattr(self, 'created_date', None):
            c_date = self.created_date
            if isinstance(c_date, str):
                try:
                    c_date = datetime.strptime(c_date, "%Y-%m-%d" if 'T' not in c_date else "%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    return True
            elif isinstance(c_date, date) and not isinstance(c_date, datetime):
                c_date = datetime.combine(c_date, datetime.min.time())
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            created_utc = c_date.replace(tzinfo=None) if hasattr(c_date, 'tzinfo') and c_date.tzinfo else c_date
            if (now_utc - created_utc).days < min_age_days:
                return False
        return True


# ---------------------------------------------------------------------------
# Canonical Cell Parser (Phase 2.1)
# ---------------------------------------------------------------------------

# Lazy re-signing hook — no-op until Phase 4.3 registers integrity_check
_post_write_hook: Callable[[str], None] = lambda path: None


def register_write_hook(hook_fn: Callable[[str], None]) -> None:
    """Register a post-write hook (e.g., manifest re-signing)."""
    global _post_write_hook
    _post_write_hook = hook_fn


def parse_cell_file(filepath: str) -> Tuple[dict, str]:
    """Parse a cell markdown file into (frontmatter_dict, body_text).

    The single source of truth for YAML frontmatter parsing.
    All enzyme files should import this instead of inline parsing.

    Args:
        filepath: Absolute or relative path to a cell .md file.

    Returns:
        Tuple of (frontmatter_dict, body_text).

    Raises:
        CellNotFoundError: If the file does not exist.
        CellParseError: If the file has no valid YAML frontmatter.
    """
    if not os.path.isfile(filepath):
        raise CellNotFoundError(f"Cell file not found: {filepath}")

    # utf-8-sig: PowerShell 5.1 `Set-Content -Encoding UTF8` writes a BOM.
    with open(filepath, encoding='utf-8-sig') as f:
        content = f.read()

    if not content.startswith('---'):
        raise CellParseError(f"No frontmatter delimiter in {filepath}")

    end_idx = content.find('---', 3)
    if end_idx == -1:
        raise CellParseError(f"Unclosed frontmatter in {filepath}")

    yaml_text = content[3:end_idx].strip()
    try:
        frontmatter = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise CellParseError(f"Invalid YAML in {filepath}: {e}") from e

    if not isinstance(frontmatter, dict):
        raise CellParseError(f"Frontmatter is not a mapping in {filepath}")

    # Body is everything after the closing ---
    body = content[end_idx + 3:].lstrip('\n')

    return frontmatter, body


def write_cell_frontmatter(
    filepath: str,
    frontmatter: dict,
    body: str,
) -> None:
    """Write a cell file with YAML frontmatter and body text.

    Calls the registered post-write hook (no-op until Phase 4.3).

    Args:
        filepath: Path to write the cell file.
        frontmatter: Dict to serialize as YAML frontmatter.
        body: Markdown body text.
    """
    yaml_text = yaml.dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('---\n')
        f.write(yaml_text)
        f.write('---\n')
        if body:
            f.write(body)

    _post_write_hook(filepath)


def _sanitize_cell_id(cell_id: str) -> str:
    """Validate cell_id against path traversal attacks.

    Raises:
        CellPathTraversalError: If cell_id contains '..' or starts with '/'.
    """
    if '..' in cell_id or cell_id.startswith('/'):
        raise CellPathTraversalError(f"Invalid cell_id: {cell_id}")
    return cell_id


def load_cell(
    cell_id: str,
    cells_dir: Optional[str] = None,
) -> Cell:
    """Load a Cell by its ID from the cells directory.

    Args:
        cell_id: Cell identifier (filename without extension).
        cells_dir: Path to .soma/cells/ directory. Defaults to auto-detect.

    Returns:
        A Cell dataclass instance.

    Raises:
        CellPathTraversalError: If cell_id contains path traversal.
        CellNotFoundError: If no matching cell file is found.
        CellParseError: If the cell file is malformed.
    """
    cell_id = _sanitize_cell_id(cell_id)

    if cells_dir is None:
        # Walk up from CWD to find .soma/cells/
        cwd = os.getcwd()
        candidate = os.path.join(cwd, '.soma', 'cells')
        if os.path.isdir(candidate):
            cells_dir = candidate
        else:
            raise CellNotFoundError(
                f"Cannot find .soma/cells/ from {cwd}"
            )

    # Search for cell_id.md recursively in cells_dir
    for root, _dirs, files in os.walk(cells_dir):
        for fname in files:
            if fname == f"{cell_id}.md":
                filepath = os.path.join(root, fname)
                # Verify resolved path is within cells_dir
                real_path = os.path.realpath(filepath)
                real_cells = os.path.realpath(cells_dir)
                if not real_path.startswith(real_cells):
                    raise CellPathTraversalError(
                        f"Resolved path escapes cells dir: {filepath}"
                    )
                frontmatter, _body = parse_cell_file(filepath)
                fitness_data = frontmatter.get('fitness', {})
                if isinstance(fitness_data, (int, float)):
                    fitness_data = {'score': float(fitness_data)}
                elif not isinstance(fitness_data, dict):
                    fitness_data = {}
                return Cell(
                    name=frontmatter.get('name', cell_id),
                    type=frontmatter.get('type', 'vacuole'),
                    hypothesis=frontmatter.get('hypothesis', ''),
                    prediction=frontmatter.get('prediction', ''),
                    falsification=frontmatter.get('falsification', ''),
                    target_paths=frontmatter.get('target_paths', []),
                    minimum_mode=frontmatter.get('minimum_mode', 'breeze'),
                    tags=frontmatter.get('tags', []),
                    fitness=CellFitness(
                        triggers=fitness_data.get('triggers', 0),
                        true_positives=fitness_data.get('true_positives', 0),
                        false_positives=fitness_data.get('false_positives', 0),
                        score=fitness_data.get('score'),
                        stress_survived=fitness_data.get('stress_survived', 0),
                    ),
                )

    raise CellNotFoundError(f"Cell not found: {cell_id}")

