# Backwards Compatibility Guarantee (SemVer 2.0)

> Formal commitment to stability, zero silent breaking changes, and predictable evolution starting at `v1.0.0`.

---

## 1. Scope & Guarantee

Beginning with the `v1.0.0` release, Soma strictly adheres to [Semantic Versioning 2.0.0](https://semver.org/).

### Semantic Versioning Rules
- **Patch Releases (`1.0.x`)**: Bug fixes, defect remediation, performance optimizations, and documentation updates. Zero breaking changes to any public API, CLI command, MCP tool schema, or cell frontmatter format.
- **Minor Releases (`1.x.0`)**: Backward-compatible feature additions, new MCP tools, new verification lenses, and opt-in configurations. No public API or CLI behavior will be removed or altered in a backwards-incompatible manner.
- **Major Releases (`2.0.0`)**: Breaking architectural changes. Any breaking change must undergo a minimum two-minor-version deprecation cycle with loud warnings.

---

## 2. Public API Surface

The following surfaces are classified as **Public Contracts** protected by this guarantee:

1. **Python SDK (`soma_sdk`)**:
   - `soma_sdk.Governance`
   - `soma_sdk.cells.Cell`, `CellFitness`, `parse_cell_file`
   - `soma_sdk.errors` hierarchy
2. **CLI Porcelains (`soma`)**:
   - `soma init`, `soma status`, `soma doctor`, `soma sync`
   - `soma verify` (including `--layer1-only`, `--release-gate`, `--rebuttal`)
   - `soma hook` (including install, status, upgrade)
   - `soma cell` (including create, promote, demote, list)
   - `soma handoff`
3. **MCP Server (`soma-mcp`)**:
   - All 20 registered tool names and input schemas in `soma_mcp/registry.py`.
   - Tool tier classifications (Read, Write, Execute).
   - Opt-in response projection semantics (`view`, `fields`).
4. **Cell & Governance Schema**:
   - Cell YAML frontmatter structure parsed by `SomaYAML`.
   - Field semantics for `id`, `type`, `enforcement`, `target_paths`, `fitness`, `hypothesis`, `prediction`.
   - `.soma/` filesystem directory conventions.

---

## 3. Deprecation Policy

When an existing public capability is scheduled for replacement:
1. **Notice Phase**: The feature is marked deprecated in documentation and emits a `DeprecationWarning` (or CLI warning) pointing to the modern replacement.
2. **Grace Period**: The deprecated interface remains fully functional for a minimum of two minor releases (e.g. deprecated in `1.2.0`, retained through `1.3.0`, eligible for removal only in `2.0.0`).
3. **Removal**: Deprecated interfaces will NEVER be removed in a minor (`1.x`) release.

---

## 4. Platform & Runtime Guarantees

- **Python Runtime**: Pure Python standard library with zero mandatory runtime dependencies (`dependencies = []`). Supported on Python 3.9, 3.10, 3.11, and 3.12+.
- **Operating Systems**: First-class support and continuous CI testing across Ubuntu (Linux), macOS, and Windows (Windows 11 with PowerShell 5.1+, PowerShell 7+, and Git Bash).
