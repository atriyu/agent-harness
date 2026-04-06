---
name: categorization-rules
description: Rules for categorizing and prioritizing requirements extracted from product documents
domain: extraction
applies_to: [extract]
priority: 1
tags: [requirements, categorization, priority, extraction]
---

## Requirement Categorization Rules

### Category Definitions
- **vpn**: VPN tunnel, encryption, protocols (WireGuard/OpenVPN/IKEv2), leak prevention, kill switch, key management
- **l4**: TCP/UDP handling, load balancing algorithms, NAT (SNAT/DNAT), connection tracking, port forwarding, health checks
- **l7**: HTTP/HTTPS routing, TLS termination, WAF rules, content-based routing, session affinity, caching, SNI
- **performance**: Throughput, latency, jitter, packet loss, scalability, connection limits, RPS targets
- **security**: Encryption standards, authentication, vulnerability protection, rate limiting, access control, certificate management
- **ha**: Failover, redundancy, state replication, health monitoring, recovery, split-brain prevention

### Priority Rules
- **P0 (Critical)**: Security vulnerabilities, data leaks, complete feature failures, authentication bypass
- **P1 (High)**: Core functionality, performance below minimum thresholds, features with "MUST" or "SHALL"
- **P2 (Medium)**: Edge cases, non-critical features, secondary protocols, features with "SHOULD"
- **P3 (Low)**: Nice-to-have, UI/UX, logging, monitoring, features with "MAY"

### Extraction Rules
1. Each requirement MUST be independently testable and verifiable
2. Split compound requirements (with "and") into separate atomic requirements
3. Extract BOTH explicit requirements ("MUST", "SHALL") and implicit ones (acceptance criteria, performance targets)
4. Include negative requirements (what the system must NOT do)
5. Capture quantitative thresholds as separate performance/security requirements
6. If a section contains no testable requirements, skip it
