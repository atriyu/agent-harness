---
name: failure-patterns
description: Common failure patterns and classification heuristics for networking product test failures
domain: triage
applies_to: [triage, repair]
priority: 2
tags: [triage, patterns, heuristics, classification]
---

## Failure Classification Heuristics

### Test Code Bugs (repairable)
- `ImportError` / `ModuleNotFoundError`: wrong import path, missing dependency
- `SyntaxError`: malformed generated code
- `NameError`: undefined variable, typo in function name
- `AttributeError`: calling method that doesn't exist on the object
- `TypeError`: wrong argument types, missing required arguments
- `fixture` in traceback: missing or misconfigured pytest fixture
- `conftest` in traceback: conftest.py issue

### Infrastructure Issues
- `ConnectionRefusedError` + topology node address: node/service not running
- `TimeoutError` + `connect`: network unreachable or topology not deployed
- `PermissionError` + `/var/run` or socket: insufficient privileges
- `docker` in error: container not started, image not pulled
- `containerlab` in error: topology deployment failed

### Configuration Errors
- `FileNotFoundError` + config path: missing configuration file
- `KeyError` in YAML/JSON parsing: wrong config structure
- `Invalid address` or `bind failed`: port conflict

### Product Bugs (the ones we're actually looking for)
- `AssertionError` where test logic is correct: product returned unexpected value
- Timeout in product operation (not in test setup): product is hanging
- Wrong HTTP status code: product routing/WAF incorrect
- Encryption verification failed: product not encrypting traffic
- Leak detected: product leaking DNS/IP traffic outside tunnel
- Performance below threshold: product not meeting SLA

### Intermittent / Flaky
- Different result on retry
- Timing-sensitive assertions (latency within 1ms of threshold)
- Race conditions in concurrent tests
- DNS resolution failures (transient)
