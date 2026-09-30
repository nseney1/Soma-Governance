---
activation: |
  Changes touching: enzymes/outcome_engine.py, enzymes/cell_fitness.py,
  enzymes/cell_escaped_defects.py, soma_mcp/jit_engine.py,
  immune_system/verification/*, enzymes/cell_create*.py,
  enzymes/cell_promote.py, enzymes/insight_*.py, install/hooks/*
enforcement: gate
---

# Core Change Protocol

Sensitive governance systems **must** follow the full TDD Protocol
(see `genome/.oracles/tdd-protocol.md`) without exception.

These files control cell fitness scoring, rule lifecycle, and verification verdicts.
A bug here doesn't just break a feature — it corrupts the governance layer's ability
to detect future bugs. The blast radius is recursive.

No trivial-change exemption applies to files in this activation list.
