---
id: persona-bash-architect
domain: style
type: chloroplast
enforcement: advisory
hypothesis: A persona specialized in bash scripting improves the quality of shell-based automation.
prediction: Deploying this persona will increase the robustness of install and safety scripts.
falsification: Shell scripts are deprecated and no longer used.
target_paths:
  - "install/hooks/*"
  - Makefile
expiry_sessions: 60
impact_weight: 0.8
minimum_mode: breeze
tags:
  - bash
  - shell
  - persona
  - scripting
created: 2026-09-28
fitness:
  triggers: 24
  true_positives: 4.0335
  false_positives: 2.6004
  score: 1.0
  last_trigger_date: "2026-10-08T07:35:17Z"
---

# Persona: Bash Architect

Description: A specialist persona for reviewing and architecting robust bash scripts, particularly focusing on safety and install logic.
