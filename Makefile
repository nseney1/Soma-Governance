# Soma — Makefile
# Without soma.conf, all defaults apply (solo/trunk/all).

# Defaults (namespaced to avoid env collisions)
SOMA_PLATFORM ?= gemini
TEAM_SIZE         ?= solo
GIT_STRATEGY      ?= trunk
APPROVAL_CHAIN    ?= none
RULES_SUBSET      ?= all
ENABLE_HOOKS      ?= true

export TEAM_SIZE GIT_STRATEGY APPROVAL_CHAIN
export RULES_SUBSET ENABLE_HOOKS SOMA_PLATFORM

# A working Python 3.9+ (python3 can be the Windows Store stub, BUG-037).
# Not exported: install.sh resolves its own, so a working python3 still
# lands in MCP configs as the portable "python3".
SOMA_PYTHON_BIN := $(shell bash -c '. enzymes/soma_python.sh && soma_resolve_python && printf %s "$$SOMA_PYTHON"' 2>/dev/null)

.PHONY: help info install install-gemini install-kiro install-copilot \
        install-claude install-mcp install-windows \
        uninstall doctor validate update status test

help: ## Show available targets
	@echo "Soma — Adaptive Governance"
	@echo ""
	@echo "Workflow:"
	@echo "  1. cp install/soma.conf.example soma.conf"
	@echo "  2. Edit soma.conf (set SOMA_PLATFORM, TEAM_SIZE, etc.)"
	@echo "  3. make install"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Override any setting inline: make install RULES_SUBSET=core"


info: ## Show current configuration
	@echo "┌───────────────────────────────┐"
	@echo "│  Soma — Configuration         │"
	@echo "├───────────────────────────────┤"
	@echo "│  Platform:        $(SOMA_PLATFORM)"
	@echo "│  Team Size:       $(TEAM_SIZE)"
	@echo "│  Git Strategy:    $(GIT_STRATEGY)"
	@echo "│  Approval Chain:  $(APPROVAL_CHAIN)"
	@echo "│  Rules Subset:    $(RULES_SUBSET)"
	@echo "│  Hooks Enabled:   $(ENABLE_HOOKS)"
	@echo "└───────────────────────────────┘"

install: ## Install for configured platform (SOMA_PLATFORM)
	@log=$$(mktemp); trap 'rm -f "$$log"' EXIT INT TERM; \
	if [ -z "$(SOMA_PYTHON_BIN)" ]; then \
	  echo "  ⚠️  no working Python 3.9+ found; skipping pip install -e . (set SOMA_PYTHON)"; \
	elif "$(SOMA_PYTHON_BIN)" -m pip install --user -e . --quiet 2>"$$log" \
	  || "$(SOMA_PYTHON_BIN)" -m pip install --user --break-system-packages -e . --quiet 2>>"$$log" \
	  || "$(SOMA_PYTHON_BIN)" -m pip install -e . --quiet 2>>"$$log"; then :; else \
	  echo "  ⚠️  pip install -e . failed (soma CLI may not be on PATH). pip reported:"; \
	  sed 's/^/      /' "$$log"; \
	fi; \
	rm -f "$$log"
	@# install.sh ends with shell-aware PATH guidance if `soma` doesn't resolve (BUG-041).
	@bash install/install.sh "$(SOMA_PLATFORM)"

install-gemini: ## Install rules for Gemini/Antigravity (alias)
	@bash install/install.sh gemini

install-kiro: ## Install rules for Kiro (alias)
	@bash install/install.sh kiro

install-copilot: ## Install rules for GitHub Copilot (alias)
	@bash install/install.sh copilot $(if $(MODE),$(MODE),global)

install-claude: ## Install rules for Claude Code
	@bash install/install.sh claude

install-mcp: ## Install only .mcp.json for any MCP-compatible agent
	@bash install/install.sh mcp

install-windows: ## Install rules and skills for Windows using PowerShell
	@powershell -ExecutionPolicy Bypass -File install/install.ps1 -Platform "$(SOMA_PLATFORM)"

uninstall: ## Remove installed genome, organs, and hooks
	@echo "Uninstalling Soma for $(SOMA_PLATFORM)..."
	@bash install/uninstall.sh "$(SOMA_PLATFORM)"

doctor: ## Verify installation health & dependencies
	@echo "Running health check..."
	@echo ""
	@echo "Dependencies:"
	@command -v bash >/dev/null 2>&1 && echo "  ✅ bash" || echo "  ❌ bash not found"
	@if [ -n "$(SOMA_PYTHON_BIN)" ]; then echo "  ✅ python ($(SOMA_PYTHON_BIN))"; else echo "  ⚠️  no working Python 3.9+ found (hooks will not install)"; fi
	@command -v git >/dev/null 2>&1 && echo "  ✅ git" || echo "  ❌ git not found"
	@command -v sed >/dev/null 2>&1 && echo "  ✅ sed" || echo "  ❌ sed not found"
	@command -v awk >/dev/null 2>&1 && echo "  ✅ awk" || echo "  ❌ awk not found"
	@echo ""
	@echo "Scripts:"
	@for s in enzymes/*.sh; do \
	  if [ -f "$$s" ]; then echo "  ✅ $$s"; else echo "  ❌ $$s missing"; fi; \
	done
	@echo ""
	@echo "Hook template:"
	@if [ -f install/hooks.json.template ]; then echo "  ✅ install/hooks.json.template"; else echo "  ❌ install/hooks.json.template missing"; fi
	@echo ""
	@echo "Installed genome ($(SOMA_PLATFORM)):"
	@case "$(SOMA_PLATFORM)" in \
	  gemini) ls $(HOME)/.gemini/config/rules/*.md 2>/dev/null | while read f; do echo "  ✅ $$(basename $$f)"; done || echo "  (none)"; \
	    if [ -f $(HOME)/.gemini/config/plugins/governance/hooks.json ]; then echo "  ✅ hooks.json installed"; else echo "  ⚠️  hooks.json not installed"; fi ;; \
	  kiro) ls $(HOME)/.kiro/steering/*.md 2>/dev/null | while read f; do echo "  ✅ $$(basename $$f)"; done || echo "  (none)"; \
	    echo ""; \
	    echo "Installed skills (kiro):"; \
	    if [ -d $(HOME)/.kiro/skills ]; then \
	      ls -d $(HOME)/.kiro/skills/*/ 2>/dev/null | while read d; do echo "  ✅ $$(basename $$d)"; done || echo="  (none)"; \
	    else echo "  (none — $(HOME)/.kiro/skills/ not found)"; fi ;; \
	  copilot) if [ -f $(HOME)/copilot-instructions.md ]; then echo "  ✅ $(HOME)/copilot-instructions.md"; else echo "  (none)"; fi ;; \
	  claude) if [ -f $(HOME)/.claude/CLAUDE.md ]; then echo "  ✅ $(HOME)/.claude/CLAUDE.md"; else echo "  (none)"; fi ;; \
	  mcp) if [ -f .mcp.json ]; then echo "  ✅ .mcp.json"; else echo "  (none)"; fi ;; \
	esac

validate: ## Check script syntax and config values
	@echo "Validating..."
	@failed=0; \
	for s in install/install.sh install/uninstall.sh enzymes/*.sh install/hooks/*; do \
	  if [ -f "$$s" ]; then \
	    if bash -n "$$s" 2>/dev/null; then echo "  ✅ $$s"; \
	    else echo "  ❌ $$s (syntax error)"; bash -n "$$s" || true; failed=1; fi; \
	  fi; \
	done; \
	if [ -n "$(SOMA_PYTHON_BIN)" ]; then \
	  for p in enzymes/*.py soma_cli/*.py soma_core/*.py soma_mcp/*.py soma_sdk/*.py immune_system/**/*.py; do \
	    if [ -f "$$p" ]; then \
	      if "$(SOMA_PYTHON_BIN)" -c "import ast, sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "$$p" 2>/dev/null; then :; \
	      else echo "  ❌ $$p (syntax error)"; failed=1; fi; \
	    fi; \
	  done; \
	  echo "  ✅ python syntax"; \
	  if "$(SOMA_PYTHON_BIN)" -c "import json, sys; json.load(open(sys.argv[1], encoding='utf-8'))" install/hooks.json.template > /dev/null 2>&1; then \
	    echo "  ✅ install/hooks.json.template (valid JSON)"; \
	  else echo "  ❌ install/hooks.json.template (invalid JSON)"; failed=1; fi; \
	else \
	  echo "  ⚠️  no working Python 3.9+ found — skipping Python syntax and JSON checks"; \
	fi; \
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true; \
	if [ "$$failed" -ne 0 ]; then echo "FAILED"; exit 1; fi; \
	echo "Done!"

update: ## Pull latest and re-install
	@echo "Pulling latest changes..."
	@git pull --ff-only
	@echo ""
	@$(MAKE) install

status: ## Show installed vs repo diff
	@echo "Comparing installed rules to repo..."
	@case "$(SOMA_PLATFORM)" in \
	  gemini) for rule in genome/*.md; do \
	    name=$$(basename $$rule); \
	    target=$(HOME)/.gemini/config/rules/$$name; \
	    if [ ! -f "$$target" ]; then echo "  ❌ $$name (not installed)"; \
	    elif diff -q "$$rule" "$$target" > /dev/null 2>&1; then echo "  ✅ $$name (in sync)"; \
	    else echo "  ⚠️  $$name (modified)"; fi; \
	  done ;; \
	  kiro) for rule in genome/*.md; do \
	    name=$$(basename $$rule); \
	    target=$(HOME)/.kiro/steering/$$name; \
	    if [ ! -f "$$target" ]; then echo "  ❌ $$name (not installed)"; \
	    else echo "  ✅ $$name (installed)"; fi; \
	  done ;; \
	  *) echo "  Status check only supported for gemini and kiro platforms" ;; \
	esac

test: validate ## Run validation tests
	@echo "Running test suite..."
	@if command -v pytest >/dev/null 2>&1; then \
	  pytest tests/ || exit 1; \
	else \
	  echo "  ❌  pytest not found. Install with: pip install pytest"; \
	  exit 1; \
	fi
