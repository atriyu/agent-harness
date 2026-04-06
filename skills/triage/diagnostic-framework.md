---
name: diagnostic-framework
description: 5-step diagnostic framework for systematic root cause analysis of test failures
domain: triage
applies_to: [triage]
priority: 1
tags: [triage, rca, diagnostic, root-cause]
---

## 5-Step Diagnostic Framework

### Step 1 — Cluster Related Failures
- Group tests sharing the same error pattern, stack trace, or failure mode
- Look for common: node names, ports, protocols, services in errors
- Tests failing with "connection refused" on the same port = one cluster
- Import/syntax errors in the same file = one cluster

### Step 2 — Classify Root Cause
Decision tree:
1. `ImportError` / `ModuleNotFoundError` / `SyntaxError` / `NameError` → **test_bug**
2. `ConnectionRefusedError` / `TimeoutError` + service not running → **infra_issue**
3. Wrong config path / missing config / permission denied → **config_error**
4. Assertion failed but test logic is correct (product returned wrong value) → **product_bug**
5. Passes on retry / non-deterministic timing → **intermittent**

### Step 3 — Assess Severity
- **critical**: Security vulnerability exposed (leak detected, plaintext found, auth bypass) OR complete feature non-functional
- **high**: Core feature degraded (tunnel unstable, LB not distributing, failover too slow)
- **medium**: Edge case failures, performance below threshold but functional
- **low**: Cosmetic, non-critical test infrastructure issues

### Step 4 — Recommend Action
- **product_bug**: "File bug: [component] - [symptom]. Blocked requirements: REQ-XXX"
- **test_bug**: "Fix test code: [file/function]. Issue: [specific fix needed]"
- **infra_issue**: "Check topology: [node] [service]. Verify [what to verify]"
- **config_error**: "Update config: [what to change] in [which file]"
- **intermittent**: "Add retry/increase timeout for [test]. If persists, investigate [what]"

### Step 5 — Cross-Reference Requirements
- Map each failure cluster to the requirement IDs it blocks
- This determines which product features are at risk
- Summarize: "X clusters found, Y are product bugs (N critical). Key risk areas: [list]"
