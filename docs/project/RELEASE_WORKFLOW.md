# Soma Release Workflow (Gitflow)

> Codified release procedure for phased governance releases.
> Each phase follows this branch → PR → merge → tag → back-merge cycle.

## Release Procedure

```text
develop ──→ release/v0.XX ──→ PR to main ──→ tag v0.XX.0 ──→ back-merge to develop
```

### Steps (execute in order)

1. **Branch from develop**: `git checkout develop && git checkout -b release/v0.XX`
2. **Commit changes**: Use conventional commits and group changes logically.
3. **Version bump checklist** — update every published version source:
   - `pyproject.toml` → `version = "0.XX.0"`
   - `VERSION` → `0.XX.0`
   - `README.md` → version badge
   - `soma_sdk/__init__.py` → `__version__ = "0.XX.0"`
   - `soma_sdk_js/package.json` → `"version": "0.XX.0"`
   - Run `pytest tests/test_static_invariants.py::test_version_is_single_sourced` and the release-specific checks.
4. **Push branch**: `git push -u origin release/v0.XX`
5. **Create PR**: `gh pr create --base main --head release/v0.XX --title "release(v0.XX): <summary>"`
6. **Wait for CI**: All matrix jobs must pass before merge. CI builds one wheel and one sdist, records `dist/SHA256SUMS`, verifies the digests in downstream jobs, and smoke-tests both distributions from outside the source checkout with `PYTHONPATH` unset and isolated Python mode. The `test-windows` job runs the full pytest suite on `windows-latest` (Python 3.9 and 3.12) under Git Bash, with `HOME` and `USERPROFILE` set to a directory under `runner.temp` (BUG-010) and `PYTHONUTF8=0`, so the cp1252 defaults Windows users hit are exercised. Its failures fail the job; any Windows failure is a regression.
7. **⛔ HUMAN REVIEW GATE**: Stop here. The maintainer reviews the PR and merges via GitHub UI. Agents must not merge directly to `main`.
8. **Tag release** (after merge): `git checkout main && git pull && git tag -a v0.XX.0 -m "<message>" && git push origin v0.XX.0`
9. **Back-merge to develop**: `git checkout develop && git merge main -m "sync: merge main back to develop after v0.XX" && git push origin develop`
10. **Create GitHub Release**: `gh release create v0.XX.0 --title "v0.XX.0 — <Theme>" --notes "<release notes>"`
11. **Publish the validated artifacts**: the release event runs `publish.yml`. It downloads the artifact that validation produced, verifies `SHA256SUMS` again, copies only the verified wheel and sdist into `publish-dist/`, and uploads them with `pypa/gh-action-pypi-publish` through **PyPI Trusted Publishing (OIDC)**. No PyPI API token is stored in the repository. The publish job runs in the `pypi` GitHub environment with `id-token: write`, and PyPI must list this repository, `publish.yml` and environment `pypi` as a trusted publisher. The `build-wheel` job signs build provenance for both files (`actions/attest-build-provenance`), and the publish action uploads PEP 740 attestations to PyPI. Do not rebuild in the publish job. To check provenance, run `gh attestation verify <file> --repo <owner>/<repo>`.
12. **Cleanup**: `git push origin --delete release/v0.XX`

## Phase → Version Mapping

| Phase | Version | Theme |
|:------|:--------|:------|
| Phase 1 | v0.73.0 ✅ | Stop the Bleeding — claim registry and release discipline |
| Phase 2 | v0.74.0 ✅ | Foundation — canonical parser, scoring, and errors |
| Phase 3 | v0.75.0 ✅ | Credit Where Due — credit assignment and rule operators |
| Phase 4 | v0.80.0 ✅ | Consensus — quorum sensing and gate enforcement |
| Phase 4.5 | v0.81.0 ✅ | CI outcome reporting and telemetry consolidation |
| Phase 4.6 | v0.82.0 ✅ | Writer migration and documentation reconciliation |
| Phase 4.7 | v0.83.0 ✅ | JIT cell cache |
| Phase 4.8 | v0.84.0 ✅ | Bug registry |
| Phase 4.9 | v0.85.0 ✅ | Antifragile hot zones |
| Phase 5.0 | v0.89.0 ✅ | MCP execution security and release integrity |
| Phase 6.0 | v0.90.0 ✅ | Security & Hardening |

## Pre-Release Checklist

Before creating a release PR, verify:
- [ ] All phase verification-gate items pass
- [ ] `python3 enzymes/verify_readme_claims.py` passes
- [ ] `pytest tests/` passes with 0 failures
- [ ] Version is synchronized across `pyproject.toml`, `VERSION`, the README badge, `soma_sdk/__init__.py`, and `soma_sdk_js/package.json`
- [ ] Validation creates exactly one wheel and one sdist plus `SHA256SUMS`
- [ ] Source-hidden smoke tests pass for both wheel and sdist
- [ ] Publish downloads and digest-verifies the validated artifact; it does not rebuild
- [ ] Publish uses OIDC Trusted Publishing (`pypi` environment, `id-token: write`); no `PYPI_API_TOKEN` secret or `twine` step
- [ ] Build provenance attestations were created for the wheel and sdist
- [ ] Workflows keep top-level `permissions: contents: read`, and every action is SHA-pinned (`tests/test_ci_workflows.py`)
- [ ] `dependency-audit` (`pip-audit`) passes
- [ ] `test-windows` passes (the full pytest suite on Windows)

### Documentation Hygiene (mandatory per release)

Audit every documentation file for staleness and classify it as **UPDATE**, **DELETE**, or **OK**.

- [ ] `README.md` — version references and feature claims match unlocked claims
- [ ] `docs/research/abstract.md` — figures and architecture match implementation
- [ ] `docs/project/CHANGELOG.md` — contains this release
- [ ] `docs/project/ROADMAP.md` — shipped statuses match the release
- [ ] `docs/architecture/scripts.md` — counts and behavior match the source tree
- [ ] `docs/project/METRICS.md` — quantitative claims remain supported
- [ ] `docs/architecture/mechanism_design.md` — architecture matches current code
- [ ] `docs/project/CLAIM_REGISTRY.json` — unlocked claims have passing tests
- [ ] `docs/project/CONTRIBUTING.md` — setup and dependencies remain current
- [ ] `docs/project/RELEASE_WORKFLOW.md` — procedure and lessons remain current
- [ ] `docs/archive/` — stale archives are reviewed

**Rule**: If a document references a version older than `current - 2`, update it or archive it unless the old version is intentionally historical.

### Post-Release Cleanup (after back-merge)

- [ ] Delete the merged release branch
- [ ] Delete stale feature branches merged into develop
- [ ] Verify `docs/project/CHANGELOG.md` has the release entry
- [ ] Verify GitHub Release notes match the PR body
- [ ] Verify the published files match the recorded release digests

## Lessons Learned

### v0.73
- `VERSION` was missed during a version bump. Keep the version-source checklist explicit.
- If a fix lands after a PR is merged, use the normal reviewed workflow rather than bypassing the human gate.

### v0.74
- A property test changed the measured proportion instead of scaling it; preserve the invariant under test.
- Documentation needs an explicit release audit, not an assumed one.

### v0.75
- `VERSION` drift recurred, confirming that version synchronization must be mechanically checked.
- Package metadata retained a stale changelog URL after a documentation move.

### v0.80
- An agent merged directly to `main`; the human review gate is now explicit.
- Read-only subagent edits failed silently; verify concrete file outputs before committing.

### v0.89
- Testing the checkout did not prove the published distributions. Build once, record digests, smoke-test wheel and sdist with the source hidden, and publish those exact bytes without rebuilding.
