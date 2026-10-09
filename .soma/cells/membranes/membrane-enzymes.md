---
id: membrane-enzymes
domain: governance
type: membrane
enforcement: advisory
hypothesis: Core enzymes and workflows dictate agent behavior.
prediction: Maelstrom mode enforcement here guarantees safe behavior modification.
falsification: Enzymes are purely descriptive and have no operational power.
target_paths:
  - "soma_core/**"
  - ".github/workflows/**"
expiry_sessions: 80
impact_weight: 1.0
minimum_mode: maelstrom
tags:
  - enzymes
  - workflows
  - review-escalation
created: 2026-09-28
fitness:
  triggers: 45
  true_positives: 10.9945
  false_positives: 15.8703
  score: 0.5
  last_trigger_date: "2026-10-09T04:28:57Z"
---

# Membrane: Enzymes Escalation

Target: `enzymes/`, `.github/workflows/`
Minimum Mode: maelstrom

Description: Escalation membrane for enzymes and workflows (`enzymes/cell_enforce.py`, `enzymes/cell_promote.py`, `enzymes/outcome_engine.py`, etc.), requiring Maelstrom+ review protocols.
