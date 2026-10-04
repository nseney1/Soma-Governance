# Soma Quickstart Guide

## What Soma Does

Soma is a governance framework for AI coding agents. It installs governance rules, provides a CLI and MCP server, and records evidence for adaptive rule management.

## Installation

Choose the option that matches your environment.

### Option 1: Install the CLI from PyPI

**Requires:** Python 3.9+ and `pip`.

```bash
pip install soma-governance
```

### Option 2: Editable source install

**Requires:** Git, Python 3.9+, and `pip`.

```bash
git clone https://github.com/nseney1/Soma-Governance.git
cd Soma-Governance
pip install -e .
```

### Option 3: Install CLI and agent integration with Make

**Requires:** Git, Python 3.9+, `pip`, Bash, and GNU Make.

```bash
git clone https://github.com/nseney1/Soma-Governance.git
cd Soma-Governance
make install SOMA_PLATFORM=gemini
```

> **PEP 668 (externally managed Python)?** Use an isolated virtual environment. If that is not possible, `pip install --user soma-governance` may be appropriate for your system.

> **Tip:** for a user-wide CLI, `pipx install soma-governance` keeps Soma in its own environment and `pipx ensurepath` puts it on `PATH` for you.

### Verify the install

```bash
soma --version
soma doctor
```

### `soma: command not found`?

`pip install --user` puts `soma` in your user scripts directory (`~/.local/bin` on Linux), which is often not on `PATH`. zsh in particular does not read `~/.profile`. Run `python3 -m soma_cli doctor` (use `python` on Windows): it prints the directory and the exact line for your shell. Typical fixes:

| Shell | Add to | Line |
|:--|:--|:--|
| zsh | `~/.zshrc` | `export PATH="$HOME/.local/bin:$PATH"` |
| bash | `~/.bashrc` (macOS: `~/.bash_profile`) | `export PATH="$HOME/.local/bin:$PATH"` |
| fish | `~/.config/fish/config.fish` (or `$XDG_CONFIG_HOME/fish/config.fish`) | `fish_add_path $HOME/.local/bin` |
| PowerShell | user `Path` variable | the `[Environment]::SetEnvironmentVariable(...)` line printed by `soma doctor` |

Open a new terminal afterwards. Until then, `python3 -m soma_cli <command>` works anywhere `soma` would.

Prefer not to edit the file yourself? `python3 -m soma_cli doctor --fix-path` shows the exact file and line it would append (a dry run); add `--yes`, or answer `y` at its prompt, to apply it. It works for zsh, bash and fish only, marks the line `# added by soma doctor --fix-path`, does nothing if the line is already there, and records it so `install/uninstall.sh` removes exactly that line again. The installers themselves never edit your dotfiles, and `--fix-path` never touches a PowerShell `$PROFILE`.

If `git commit` fails with a soma pre-commit message, the hook could not find `soma` either: fix `PATH` as above, then re-run `soma init` to refresh the hook (BUG-047).

## First Run with `soma init`

`soma init` detects Gemini, Claude Code, Cursor, and Copilot markers. If detection is ambiguous, select one of those platforms explicitly.

```bash
soma init --platform gemini --yes
soma status
# ... do a coding session ...
soma report
```

Useful setup flags verified by `soma --help`:

```bash
soma init --dry-run
soma init --rules minimal --platform claude
soma init --rules standard --mcp --platform cursor --yes
soma init --rules full --platform copilot --force --yes
```

## Kiro and Generic MCP Installation

Kiro is supported by the Bash installer; it is not auto-detected by `soma init`.

```bash
bash install/install.sh kiro --dry-run
bash install/install.sh kiro
```

For any MCP-compatible agent, generate a project-local `.mcp.json` with the Bash installer:

```bash
bash install/install.sh mcp --dry-run
bash install/install.sh mcp
```

## CLI Commands

```bash
# Governance lifecycle
soma init --help        # Set up governance for a supported detected/selected platform
soma status             # Show active rules and fitness stats
soma report             # Session report card
soma doctor             # Verify installation integrity

# Quality gates
soma checkpoint         # Deterministic quality checks
soma checkpoint --pre-commit --strict
soma verify --layer1-only

# Evidence pipeline
soma sync               # Reconcile JSONL evidence with cell frontmatter
soma sync --dry-run --json

# Cell lifecycle
soma genesis --dry-run
soma oracle --json
soma promote --dry-run
soma demote --dry-run
```

## Shell completion

`soma completion <shell>` prints a completion script for `bash`, `zsh` or `fish`. It is generated from the CLI's own argument parser each time, so it always matches your installed version. Soma never edits your dotfiles: add the line yourself, then open a new terminal.

| Shell | Add to | Line |
|:--|:--|:--|
| zsh | `~/.zshrc` (after `compinit`; oh-my-zsh runs it for you) | `eval "$(soma completion zsh)"` |
| bash | `~/.bashrc` | `eval "$(soma completion bash)"` |
| fish | `~/.config/fish/config.fish` | `soma completion fish \| source` |

Without oh-my-zsh, put `autoload -Uz compinit && compinit` before the zsh line. To avoid running `soma` at every shell start, save the script once instead, e.g. `soma completion zsh > ~/.zfunc/_soma` (with `~/.zfunc` on your `fpath`) or `soma completion fish > ~/.config/fish/completions/soma.fish`, and re-run it after upgrading Soma.

## Make Targets

The repository Makefile provides `help`, `info`, `install`, `install-gemini`, `install-kiro`, `install-copilot`, `install-claude`, `install-mcp`, `install-windows`, `uninstall`, `doctor`, `validate`, `update`, `status`, and `test`. Run `make help` for descriptions.

## What the Standard Starter Rules Do

- `providence`: grounds claims in evidence and requires read-before-write.
- `destructive-ops`: requires safety gates for dangerous operations.
- `testing`: requires behavioral tests and meaningful failure coverage.
- `cost-optimization`: limits wasted tokens and compute without sacrificing correctness.
- `git-workflow`: defines safe, consistent Git practices.

## Next Steps

See [README.md](README.md) for MCP configuration, receipt usage, SDK examples, and architecture details.
