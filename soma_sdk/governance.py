"""Core Governance API."""
import json
import subprocess
import sys
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


class Governance:
    """Soma governance interface.
    
    Usage:
        from soma_sdk import Governance
        gov = Governance(project_root='.')
        
        landscape = gov.fitness_landscape(bayesian=True)
        coverage = gov.coverage_report()
        replay = gov.replay(commits=20)
        grade = gov.grade()
    """
    
    def __init__(self, project_root='.'):
        self.root = Path(project_root).resolve()
        self.cells_dir = self.root / '.soma' / 'cells'
        self.metrics_dir = self.root / '.soma' / 'metrics'
        self.scripts_dir = self._find_scripts_dir()
    
    def _find_scripts_dir(self):
        """Locate Soma scripts directory."""
        candidates = [
            self.root / 'vendor' / 'soma' / 'enzymes',
            self.root / 'enzymes',
            Path(__file__).parent.parent / 'enzymes',
        ]
        for c in candidates:
            if c.is_dir() and (c / 'cell_fitness.py').exists():
                return c
        return None
    
    def _run_script(self, script_name, *args, json_output=True):
        """Run a Soma enzyme script and return parsed output."""
        if not self.scripts_dir:
            raise RuntimeError('Soma enzymes directory not found')
        
        script = self.scripts_dir / script_name
        if not script.exists():
            raise FileNotFoundError(f'Script not found: {script_name}')
        
        if script.suffix == '.sh':
            cmd = ['bash', str(script)] + list(args)
        else:
            cmd = [sys.executable, str(script)] + list(args)
        if json_output:
            cmd.append('--json')
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.root))
        if result.returncode != 0:
            err_msg = result.stderr.strip() or result.stdout.strip()
            if json_output:
                return {'error': f'Command failed with exit code {result.returncode}', 'details': err_msg}
            else:
                raise RuntimeError(f'Command failed with exit code {result.returncode}: {err_msg}')
                
        if json_output and result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {'raw': result.stdout, 'error': 'JSON parse failed'}
        return result.stdout
    
    # === Cell Management ===
    
    def list_cells(self):
        """List all immune cells."""
        cells = []
        if not self.cells_dir.exists():
            return cells
        for cell_file in self.cells_dir.rglob('*.md'):
            if cell_file.name == 'README.md': continue
            try:
                content = cell_file.read_text()
                if not content.startswith('---'): continue
                fm = yaml.safe_load(content[3:content.find('---', 3)])
                fm['_name'] = cell_file.stem
                fm['_path'] = str(cell_file.relative_to(self.root))
                cells.append(fm)
            except Exception: pass
        return cells
    
    def create_cell(self, hypothesis, type='vacuole', target_paths=None,
                    minimum_mode='breeze', tags=None, cell_id=None):
        """Create a new immune cell."""
        raw_slug = cell_id or hypothesis[:40]
        safe_slug = re.sub(r'[^a-zA-Z0-9_.-]', '-', raw_slug).strip('-')
        
        args = ['--id', safe_slug, '--type', type,
                '--hypothesis', hypothesis]
        if target_paths:
            args.extend(['--target-paths', ','.join(target_paths)])
        if minimum_mode != 'breeze':
            args.extend(['--minimum-mode', minimum_mode])
        if tags:
            args.extend(['--tags', ','.join(tags)])
        
        return self._run_script('cell_create.sh', *args, json_output=False)
    
    def create_cell_from_description(self, description, domain=None, cell_type=None):
        """Create a cell using natural language via Gemini API."""
        args = [description]
        if domain:
            args.extend(['--domain', domain])
        if cell_type:
            args.extend(['--type', cell_type])
        return self._run_script('cell_create_nl.py', *args, json_output=False)
    
    def signal(self, cell_name, signal_type, metric=None):
        """Send a fitness signal to a cell.
        
        Args:
            cell_name: Name of the cell to signal
            signal_type: 'tp' (true positive) or 'fp' (false positive)
            metric: Optional dict of metrics, e.g. {'survival_day': 12}
        """
        args = [cell_name, signal_type]
        if metric:
            for k, v in metric.items():
                args.extend(['--metric', f'{k}={v}'])
        
        return self._run_script('cell_signal.sh', *args, json_output=False)
    
    # === Analysis ===
    
    def fitness_landscape(self, bayesian=False):
        """Get fitness scores for all cells."""
        args = []
        if bayesian:
            args.append('--bayesian')
        return self._run_script('cell_fitness.py', *args)
    
    def coverage_report(self, exclude=None):
        """Get cell coverage report."""
        args = []
        if exclude:
            args.extend(['--exclude', exclude])
        return self._run_script('cell_coverage.py', *args)
    
    def replay(self, commits=20):
        """Replay governance against historical commits."""
        return self._run_script('immune_replay.py', '--commits', str(commits))
    
    def trends(self, days=30):
        """Get cross-session governance trends."""
        return self._run_script('immune_trends.py', '--days', str(days))
    
    def grade(self):
        """Get governance report card."""
        return self._run_script('immune_grade.py')
    
    def quorum(self, threshold=3):
        """Check for quorum (systemic multi-cell triggers)."""
        return self._run_script('cell_quorum.py', '--threshold', str(threshold))
    
    def dependencies(self, format='text'):
        """Get cell dependency graph."""
        return self._run_script('cell_deps.py', '--format', format, json_output=(format != 'mermaid'))
    
    def scan(self):
        """Scan current diff against cells."""
        return self._run_script('cell_scan.py')
