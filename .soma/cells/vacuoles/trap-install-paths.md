---
id: trap-install-paths
domain: correctness
type: vacuole
enforcement: advisory
hypothesis: Install scripts have divergent paths.
prediction: Unifying install targets will prevent deployment errors.
falsification: The paths are intentionally distinct for separate deploy targets.
target_paths:
  - "soma_cli/platforms/*.py"
  - Makefile
expiry_sessions: 40
impact_weight: 0.9
minimum_mode: breeze
tags:
  - install
  - paths
  - correctness
created: 2026-09-28
fitness:
  triggers: 24
  true_positives: 1.9535
  false_positives: 3.0804
  score: 0.5
  last_trigger_date: "2026-10-09T04:28:57Z"
---

# Trap: Install Paths Divergence

Target: `install/install.sh` vs `Makefile`

Description: Install targets diverge (`~/.gemini/config/rules/` vs `~/.gemini/config/genome/`). These need to be unified or clearly documented if intentionally separated.
