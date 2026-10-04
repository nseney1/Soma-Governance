# Soma

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)
[![Core Rules](https://img.shields.io/badge/Core_Rules-18-green?style=flat-square)](#-core-rules)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-15-purple?style=flat-square)](#-agent-skills)
[![Automation Scripts](https://img.shields.io/badge/Automation_Scripts-62-red?style=flat-square)](#%EF%B8%8F-automation-scripts)
[![Adaptive Rules](https://img.shields.io/badge/Adaptive_Rules-5_Types-orange?style=flat-square)](#-adaptive-rules)
[![Version](https://img.shields.io/badge/Version-0.90.0-informational?style=flat-square)](docs/project/CHANGELOG.md)
[![Blog Post](https://img.shields.io/badge/Blog-dev.to-black?style=flat-square&logo=devdotto)](https://dev.to/nseney1/rules-that-cant-prove-themselves-die-adaptive-governance-for-ai-coding-agents-25bn)
[![Blog Post 2](https://img.shields.io/badge/Blog_2-dev.to-black?style=flat-square&logo=devdotto)](https://dev.to/nseney1/your-ai-agents-rules-file-is-a-gentlemans-agreement-heres-what-happens-when-you-make-3df5)

**Governance framework that makes AI coding agents trustworthy.**

Soma makes AI agents trustworthy by providing observably traceable governance — evidence-based rule selection, AST analysis tools, and adaptive rule lifecycle management. Rules that stop proving themselves expire. Rules that keep proving themselves get promoted. Claims that don't match evidence are caught.

> **The Problem**: Ungoverned AI coding agents waste significant portions of tokens in circular rework loops, hallucinated API calls, and broken assumptions. Static rule files (`.cursorrules`, `CLAUDE.md`) help but never adapt, and the agent can simply ignore them.
>
> **The Solution**: Soma provides JIT context injection, adaptive rule lifecycle, and pre-commit enforcement hooks to reduce waste. Rules are scored by Wilson-bounded fitness intervals and pruned when they stop proving value.

> **Internal naming convention**: Soma uses a biological metaphor internally (genome, enzymes, organs, cells) to model rule evolution — see the codebase for details.

See the [NOTICE](NOTICE) file for our full local-only Data Privacy Statement.

---

## Quick Start

### Install

```bash
# Clone
git clone https://github.com/nseney1/Soma-Governance.git && cd Soma-Governance

# Install the CLI (Python 3.9+)
pip install -e .

# Or install from PyPI
pip install soma-governance

# Set up governance (auto-detects Gemini, Claude Code, Cursor, or Copilot)
soma init --yes

# See what's active
soma status
```

> **`soma: command not found`** (common under zsh after `pip install --user`)? Run `python3 -m soma_cli doctor` for the exact `PATH` line for your shell, or see [QUICKSTART.md](QUICKSTART.md#soma-command-not-found).

<details>
<summary>Alternative install methods</summary>

```bash
# Global install via Makefile (Gemini / Antigravity)
make install

# Shell installer for specific platforms
bash install/install.sh gemini     # Google Gemini
bash install/install.sh copilot    # GitHub Copilot
bash install/install.sh claude     # Claude Code
bash install/install.sh kiro       # AWS Kiro
bash install/install.sh mcp        # Any MCP-compatible agent
```

</details>

### MCP Server (Recommended)

Add Soma as an MCP server in your AI agent's config. Set `SOMA_WORKSPACE` to the governed project (the directory containing `.soma/cells/`). No API key is needed because the host agent supplies the model.

```json
{
  "mcpServers": {
    "soma": {
      "command": "python3",
      "args": ["-m", "soma_mcp"],
      "env": {
        "SOMA_WORKSPACE": "/path/to/your/project",
        "SOMA_EXECUTION_ENABLED": "1"
      }
    }
  }
}
```

Works with Gemini Antigravity, Claude Code, Cursor, and any MCP-compatible agent.

**Capabilities:** With `SOMA_EXECUTION_ENABLED` omitted, the server exposes six read tools and three write tools. Write tools are discoverable but require a receipt. Setting `SOMA_EXECUTION_ENABLED=1` additionally exposes six execute tools, which also require receipts.

| Tier | Available tools |
|:-----|:----------------|
| Read (default) | `soma_request_receipt`, `soma_scan`, `soma_list_cells`, `soma_grade`, `soma_coverage`, `soma_fitness` |
| Write (default; receipt required) | `soma_report_outcome`, `soma_capture_insight`, `soma_create_cell` |
| Execute (opt-in; receipt required) | `soma_propose_change`, `soma_verify_changes`, `soma_checkpoint`, `soma_audit_security`, `soma_audit_performance`, `soma_generate_manifest` |

**Receipt flow for write and execute tools:**

1. Call `soma_request_receipt` with the intended tool name in `operation` and the exact tool arguments in `arguments`. For `soma_report_outcome`, those arguments must include a non-empty, retry-stable `idempotency_key`.
2. Call that tool with the same arguments plus the returned `receipt`.

Receipts expire after 300 seconds and are single-use. They are bound to the current MCP session, canonical workspace, operation, exact arguments, target-file state, and governance-cell state. If a target file or any cell changes before redemption, request a new receipt. Receipts authorize a specific state-bound operation; they do not authenticate a person. Reusing the same `soma_report_outcome` idempotency key with the same payload is a no-op; changing the payload for that key fails closed.

### SDK

```bash
pip install soma-governance        # Python
npm install soma-governance        # JavaScript / TypeScript
```

```python
from soma_sdk import Governance

gov = Governance(project_root='.')
landscape = gov.fitness_landscape(bayesian=True)
coverage = gov.coverage_report()
grade = gov.grade()
gov.signal('wall-gae-truncation', 'tp', metric={'survival_day': 12})
```

```javascript
const { Governance } = require('soma-governance');
const gov = new Governance('.');
const grade = await gov.grade();
const entropy = await gov.entropy();
```

---

## CLI Commands

All governance workflows are available via the `soma` CLI:

| Command | Description |
|:--------|:------------|
| `soma init` | Set up governance for Gemini, Claude Code, Cursor, or Copilot; use the Bash installer for Kiro |
| `soma genesis` | Scan codebase architecture, generate governance cells |
| `soma status` | Show active rules, cell counts, and fitness stats |
| `soma report` | Session report card with compliance metrics |
| `soma doctor` | System health check — verifies installation integrity |
| `soma verify` | Layer 1 AST analysis on changed files (`--layer1-only` available) |
| `soma checkpoint` | Quality checks (`--pre-commit` for git hooks) |
| `soma sync` | Reconcile evidence JSONL with cell frontmatter (`--dry-run`, `--json`) |
| `soma oracle` | Cell health classification — healthy, noisy, expired, unobserved |
| `soma promote` | Evaluate cells for promotion (vacuole → wall → genome). `--force --cell <id>` for manual |
| `soma demote` | Evaluate cells for demotion (high FP rate or dormant). `--force --cell <id>` for manual |

```bash
# Quick quality check before committing
soma checkpoint

# AST analysis (Layer 1)
soma verify

# Cell health dashboard
soma oracle --json

# See what cells earned promotion
soma promote --dry-run
```

---

## Architecture

Soma models governance as a layered system of rules, skills, and automation. Every component maps to a specific role:

```text
┌──────────────────────────────────────────────────────────────────────┐
│  📐 CORE RULES (genome/)          18 Rules — inherited defaults      │
│  🔧 AGENT SKILLS (organs/)       15 Skills — complex behaviors       │
│  ⚙️  AUTOMATION (enzymes/)        62 Scripts — task automation        │
├──────────────────────────────────────────────────────────────────────┤
│  🛡️ VERIFICATION                  AST analysis tools                  │
│     Layer 1: AST-based checks (import guards, complexity, coverage)  │
├──────────────────────────────────────────────────────────────────────┤
│  📋 ADAPTIVE RULES (.soma/cells/) → Per-Repo Governance             │
│     Vacuoles · Chloroplasts · Walls · Membranes · Plasmodesmata      │
└──────────────────────────────────────────────────────────────────────┘
```

| Layer | Directory | What It Contains |
|:------|:----------|:-----------------|
| **Core Rules** | `genome/` | 18 rules — inherited behavioral defaults, rarely changed. |
| **Agent Skills** | `organs/` | 15 skills — complex multi-step behaviors like adaptive-reviewer, genesis, security-audit. |
| **Automation Scripts** | `enzymes/` | 62 scripts — task-specific automation (fitness scoring, rule creation, evidence pipeline). |
| **Verification** | `immune_system/` | AST analysis tools for code checking. |
| **Adaptive Rules** | `.soma/cells/` | Per-repo adaptive invariants. Generated, tested, evolved, or retired. |

---

## 📐 Core Rules

The system's foundational rules — 18 rules that define inherited behavior. Always-on rules are loaded every session; conditional rules activate on demand.

| Rule | Trigger | Purpose |
|:-----|:--------|:--------|
| [providence](genome/providence.md) | always_on | Codebase grounding, no hallucinations, diagnose-before-repair |
| [cost-optimization](genome/cost-optimization.md) | always_on | Token efficiency, diffs-only edits, FPSR metric (>80%) |
| [subagent-delegation](genome/subagent-delegation.md) | always_on | Context protection, concurrency limits, delegation floor |
| [architectural-tenets](genome/.oracles/architectural-tenets.md) | model_decision | Pragmatism, trade-off analysis, scale-to-zero |
| [polyglot-standards](genome/.oracles/polyglot-standards.md) | model_decision | Unified entrypoints (Makefiles), containerization |
| [feature-specs](genome/.oracles/feature-specs.md) | model_decision | PRD structure, acceptance criteria, documentation |
| [testing](genome/.oracles/testing.md) | model_decision | Behavioral testing, sad paths, ast.parse ban |
| [documentation](genome/.oracles/documentation.md) | model_decision | ADRs, actionable READMEs, Mermaid diagrams |
| [destructive-ops](genome/destructive-ops.md) | model_decision | Dry-run mandates for IaC, database mutations, bulk git |
| [git-workflow](genome/.oracles/git-workflow.md) | model_decision | Conventional commits, .gitignore verification |
| [desktop-automation](genome/desktop-automation.md) | model_decision | PyAutoGUI/xdotool safety, focus verification |
| [core-change-protocol](genome/core-change-protocol.md) | model_decision | Approval gates for genome/enzyme modifications |
| [tdd-protocol](genome/.oracles/tdd-protocol.md) | model_decision | Test-driven development with sequential phase gates |
| [optional-import-guard](genome/.oracles/optional-import-guard.md) | model_decision | try/except guards on optional dependencies |
| [hgt-resource-consolidation](genome/hgt-resource-consolidation-hgt.md) | model_decision | Cross-project rule sharing governance |
| [ci-green-before-release](genome/ci-green-before-release.md) | model_decision | Requires green CI before release or deployment |
| [gitflow-review-gate](genome/gitflow-review-gate.md) | model_decision | Enforces reviewed Gitflow branch transitions |
| [no-pre-existing-excuse](genome/no-pre-existing-excuse.md) | model_decision | Requires fixing relevant pre-existing failures instead of dismissing them |

---

## 🔧 Agent Skills

Complex multi-step behaviors — each skill performs a specialized function.

| Skill | Purpose |
|:------|:--------|
| [adaptive-reviewer](organs/adaptive-reviewer/SKILL.md) | Auto-escalating review orchestrator with subagent nesting |
| [domain-researcher](organs/domain-researcher/SKILL.md) | Compiles verified external facts (wikis, API docs) |
| [genesis](organs/genesis/SKILL.md) | Codebase onboarding: scans stack and seeds governance cells |
| [governance-auditor](organs/governance-auditor/SKILL.md) | Mechanical per-rule PASS/FAIL compliance checks |
| [incident-debug](organs/incident-debug/SKILL.md) | SRE: reproduce → isolate → diagnose → fix → verify |
| [performance-audit](organs/performance-audit/SKILL.md) | Hot-path allocations, O(n²) patterns, GC pressure |
| [post-mortem](organs/post-mortem/SKILL.md) | Blameless retrospective analysis, pattern extraction |
| [readme-writer](organs/readme-writer/SKILL.md) | Scannable, copy-pasteable developer READMEs |
| [refactoring-pilot](organs/refactoring-pilot/SKILL.md) | Mikado Method, incremental moves across 4+ files |
| [security-audit](organs/security-audit/SKILL.md) | AppSec Engineer: OWASP Top 10, hardcoded secrets |
| [session-monitor](organs/session-monitor/SKILL.md) | Live waste trajectory tracking, periodic probes |
| [session-preflight](organs/session-preflight/SKILL.md) | Pre-flight: venv health, git state, test suite verification |
| [spec-synthesizer](organs/spec-synthesizer/SKILL.md) | Cross-references multi-lens findings into prioritized plans |
| [staff-review](organs/staff-review/SKILL.md) | Multi-lens fan-out (10 lenses) with staff-level synthesis |
| [visual-analyst](organs/visual-analyst/SKILL.md) | Screen & UI analysis: game state, regressions |

---

## 📋 Adaptive Rules

Adaptive rules are the per-repository governance layer — atomic, dynamically generated invariants that live exclusively inside your repository (`.soma/cells/`).

| Rule Type | Role | What It Does |
|:----------|:-----|:-------------|
| **Vacuole** | Anti-pattern trap | Catches known anti-patterns (e.g., "Don't use raw coordinates") |
| **Chloroplast** | Best-practice injector | Injects idiomatic patterns (e.g., "Use async FastAPI conventions") |
| **Cell Wall** | Non-negotiable boundary | Non-negotiable safety gate (e.g., "Never skip GAE truncation") |
| **Membrane** | Selective review trigger | Forces elevated review when sensitive areas change |
| **Plasmodesmata** | Cross-service contract | Governs data shapes and APIs between services |

### Rule Lifecycle

Adaptive rules operate on an evidence-based lifecycle:

```text
Generate → Score (Confidence Decay) → Adapt → Differentiate → Prune / Retire → Promote
   ↑                                                                               |
   └──────────────────────── External Fitness Signals (CI/CD, tests, metrics) ─────┘
```

**Lifecycle operators**: Differentiation (vacuoles harden into walls), Confidence Decay (confidence decays unless reinforced), Retirement (immediate eviction on excess false positives), Horizontal Transfer (cross-project sharing with probation), Version History (provenance tracking).

**Fitness scoring**: Wilson-bounded fitness scoring with credible intervals — cells are scored by true positive rate using Wilson score intervals for statistically rigorous confidence bounds. Laplace smoothing `(tp + 1) / (triggers + 2)` provides the point estimate; Wilson bounds determine promotion and pruning thresholds. The Python SDK and enzymes use the canonical `parse_cell_file` parser; the dependency-light MCP path uses its documented standard-library frontmatter parser.

**Credit assignment**: Scope-narrowed credit assignment with per-file conservation — when multiple cells match the same changed file, each cell's fitness signal is weighted by `1/N` (where N = matching cells for that file). Fractional credit is stored deterministically rather than randomly rounded. Canonical events are recorded in `.soma/evidence/signals.jsonl` with credit and provenance metadata.

**Structured crossover**: Structured field-level rule merging — two high-fitness cells can be crossed to produce offspring with combined hypotheses, max impact weight, merged target paths (union), and reset fitness counters. Lineage tracking records parent IDs, generation number, and creation method.

**Tournament selection**: Tournament selection for rule competition — random k-sample selection identifies the highest-fitness cell per round. Read-only operation preserves cell state. Handles null fitness, oversized k, and empty cell directories gracefully.

**Tiered enforcement**: Rules earn their enforcement tier through demonstrated defect prevention — `advisory` (prompt injection) → `mechanical` (pre-commit block) → `gate` (CI block). Enforcement ladder evaluates cell invariants and applies tier-appropriate blocking.

**Quorum sensing**: Multi-rule consensus for high-confidence decisions — when ≥N cells trigger simultaneously on the same changed files, Soma detects a systemic issue and escalates the review mode to the highest `minimum_mode` among triggered cells. Quorum events are logged to JSONL for trend analysis.

**Gate enforcement DSL**: Cells can declare invariants in frontmatter (e.g., `import_banned`, `file_must_exist`) that are evaluated against changed files. Violations are enforced according to the cell's enforcement tier: advisory warns without blocking, gate exits non-zero in CI.

> **Planned features**: See [ROADMAP.md](docs/project/ROADMAP.md) for upcoming work.

---

## ⚙️ Automation Scripts

Soma includes 62 task-specific scripts driving rule lifecycles, verification, and evidence pipelines. See [SCRIPTS.md](docs/architecture/scripts.md) for full documentation.

---

## Configuration

Copy [`soma.conf.example`](install/soma.conf.example) → `soma.conf` to customize.

| Variable | Default | Description |
|:---------|:--------|:------------|
| `SOMA_PLATFORM` | `gemini` | Target AI platform: `gemini`, `kiro`, `copilot`, `claude`, `mcp` |
| `SOMA_INFERENCE_PROVIDER` | `auto` | LLM provider: `auto`, `gemini`, `anthropic`, `openai`, `prompt-only` |
| `DEFAULT_REVIEW_MODE` | `gale` | Session default review intensity |
| `CELL_TELOMERE_DAYS` | `30` | Days for fitness confidence to halve |
| `CELL_TELOMERE_WALL` | `null` | Walls (invariants) never decay |
| `TEAM_SIZE` | `solo` | Team topology: `solo`, `small`, `team`, `enterprise` |


### Cross-OS Support

| OS | Shell | Install | Uninstall | Core Rules | Agent Skills | Hooks |
|:---|:------|:--------|:----------|:----------:|:------------:|:-----:|
| **Linux** | Bash | `make install` | `bash install/uninstall.sh` | ✅ | ✅ | ✅ |
| **macOS** | Zsh / Bash | `make install` | `bash install/uninstall.sh` | ✅ | ✅ | ✅ |
| **WSL** | Bash | `make install` | `bash install/uninstall.sh` | ✅ | ✅ | ✅ |
| **Windows (Git Bash)** | Bash | `make install` | `bash install/uninstall.sh` | ✅ | ✅ | ⚠️ |
| **Windows (PowerShell)** | PowerShell | `.\install.ps1` | `.\install\uninstall.ps1` | ⚠️ | ⚠️ | ❌ |

> **⚠ Windows known issues (open):** Under Windows PowerShell 5.1, the default for `.\install.ps1`, the installer writes mojibake into the generated rules ([BUG-014](docs/project/BUG_REGISTRY.json)); use `pwsh` to avoid it. Details and workarounds: [Known Issues — Windows](docs/KNOWN_ISSUES_WINDOWS.md).

---

## How Soma Differs

Soma replaces passive prompt files with active lifecycle-managed governance: JIT context loading prevents bloat, adaptive cells trap repo-specific bugs, and AST analysis catches violations deterministically.

For design analysis, see [ABSTRACT.md](docs/research/abstract.md).

---

## Testing & CI

### Test Suite

```bash
make test       # Full validation + pytest
make validate   # Shell syntax, Python compilation, JSON templates
make doctor     # System health check
```

See [CONTRIBUTING.md](docs/project/CONTRIBUTING.md) for test guidelines and execution instructions.

### CI/CD Pipeline

GitHub Actions runs on `ubuntu-latest`, `macos-latest`, and `windows-latest`:
- **Linux/macOS**: Shell syntax validation → Python compilation → pytest → hardcoded path audit → script count invariant (≥16) → privacy audit → dry-run install sweep (all 5 platforms) → claim registry verification
- **Windows**: PowerShell AST parsing → dry-run install with rule count assertion

### Documentation Gating

Every feature claim in this README is tracked in [`docs/project/CLAIM_REGISTRY.json`](docs/project/CLAIM_REGISTRY.json). A claim can only appear in README when:
1. Its behavioral test suite exists and passes
2. It has a Claim Registry entry with status `unlocked`
3. The CI gate (`enzymes/verify_readme_claims.py`) confirms no regressions

Features that are planned but not yet shipped are listed in [ROADMAP.md](docs/project/ROADMAP.md).

---

## Documentation

| Document | Audience | Description |
|:---------|:---------|:------------|
| [**Blog Post**](https://dev.to/nseney1/rules-that-cant-prove-themselves-die-adaptive-governance-for-ai-coding-agents-25bn) | Everyone | "Rules That Can't Prove Themselves Die" — full introduction |
| [CHANGELOG](docs/project/CHANGELOG.md) | Users | Release history |
| [Bug Registry](docs/project/BUG_REGISTRY.json) | Contributors, agents | Every known bug, fixed and open, with root cause and regression test |
| [Known Issues — Windows](docs/KNOWN_ISSUES_WINDOWS.md) | Windows users | Open Windows bugs, workarounds, and impact |
| [SECURITY](SECURITY.md) | Security researchers | Supported versions, private vulnerability reporting, scope |
| [ROADMAP](docs/project/ROADMAP.md) | Users | Planned features and their tracking status |
| [PHYLOGENY](docs/architecture/phylogeny.md) | Contributors | Phase-by-phase evolutionary narrative |
| [MECHANISM_DESIGN](docs/architecture/mechanism_design.md) | Contributors | Formal mechanism design mapping |
| [SCRIPTS](docs/architecture/scripts.md) | Contributors | Full automation script catalog |
| [METRICS](docs/project/METRICS.md) | Users | Empirical measurement methodology |
| [ABSTRACT](docs/research/abstract.md) | Researchers | Research paper abstract |
| [CONTRIBUTING](docs/project/CONTRIBUTING.md) | Contributors | Contribution guidelines |
| [Templates](templates/README.md) | Users | Domain-specific rule template packs |

## Uninstalling

```bash
bash install/uninstall.sh gemini                # Remove Soma files, restore backups
bash install/uninstall.sh gemini --dry-run       # Preview what will be removed
bash install/uninstall.sh gemini --keep-config   # Preserve soma.conf
bash install/uninstall.sh gemini --no-restore    # Skip backup restoration
bash install/uninstall.sh gemini --force         # Skip confirmation prompt
bash install/uninstall.sh gemini --purge-data    # Also remove cells, fitness history
```

On Windows (PowerShell):

```powershell
pwsh install\uninstall.ps1 -Platform gemini
pwsh install\uninstall.ps1 -Platform gemini -DryRun
```

The Bash installer auto-migrates existing `.prism/` directories to `.soma/`. `soma init` and the PowerShell installer do not perform this migration.

## License

Apache 2.0 — Copyright 2026 Nicholas Seney
See [NOTICE](NOTICE) for Data Privacy details.
