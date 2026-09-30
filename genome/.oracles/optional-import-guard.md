---
name: Optional Import Guard
description: Enforces try/except guards on optional dependencies to prevent CI and runtime crashes.
trigger: model_decision
---

# Optional Import Guard

**Role**: Prevents bare imports of optional packages that crash the module when the dependency isn't installed.

## Rule

Any `import` of a package not in the Python standard library and not listed as a **required** dependency in `pyproject.toml` or `requirements.txt` MUST be wrapped in a `try/except ImportError` guard:

```python
try:
    import yaml
except ImportError:
    yaml = None
```

## Scope

This applies to ALL files in `enzymes/`, `soma_mcp/`, `immune_system/`, and `install/`.

## Known Optional Dependencies

| Package | Used For | Fallback |
|:--------|:---------|:---------|
| `yaml` (pyyaml) | YAML frontmatter parsing | Manual parsing or `{}` |
| `anthropic` | Anthropic API provider | Skip provider |
| `google.generativeai` | Gemini API provider | Skip provider |
| `openai` | OpenAI API provider | Skip provider |

## Why This Matters

Unguarded `import yaml` has been the #1 recurring CI failure in this project. CI runs without `pyyaml` installed. A single unguarded import in ANY file transitively imported by tests crashes the entire test suite for that module.

The blast radius is recursive: `test_foo.py` imports `module_a.py` which imports `module_b.py` which has `import yaml` → ALL tests touching `module_a` fail with `ModuleNotFoundError`.

## Enforcement

When reviewing or writing code that adds an `import` statement:

1. Check if the package is in the standard library → if yes, bare import is fine
2. Check if it's a required dependency in `pyproject.toml` → if yes, bare import is fine
3. Otherwise → MUST use `try/except ImportError` guard

## Violation Detection

```bash
# Find all unguarded optional imports
grep -rn '^import yaml$' enzymes/ soma_mcp/ immune_system/ --include='*.py'
```

Any match is a violation. The correct form will show up as `import yaml` indented under `try:`.
