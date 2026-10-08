---
id: membrane-install
domain: governance
type: membrane
enforcement: advisory
hypothesis: Install scripts represent high-risk operations requiring elevated governance.
prediction: Enforcing maelstrom mode for install operations prevents unsafe system changes.
falsification: Install scripts operate in a fully sandboxed environment with no persistent effects.
target_paths:
  - "install/**"
expiry_sessions: 80
impact_weight: 1.0
minimum_mode: maelstrom
tags:
  - install
  - deployment
  - review-escalation
created: 2026-09-28
fitness:
  triggers: 5
  true_positives: 2.2
  false_positives: 0.4
  score: 1.0
  last_trigger_date: "2026-10-08T07:19:48Z"
---

# Membrane: Install Escalation

Target: `install/`
Minimum Mode: maelstrom

Description: Escalation membrane for install and uninstall scripts, requiring Maelstrom+ review protocols.
