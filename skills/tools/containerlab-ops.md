---
name: containerlab-ops
description: Containerlab topology selection rules and operations for test execution
domain: infrastructure
applies_to: [plan, codegen]
priority: 3
tags: [containerlab, topology, infrastructure]
---

## Topology Selection Rules

### Available Topologies
- **vpn_basic**: VPN gateway + client + server (WireGuard :51820, OpenVPN :1194, IKEv2 :500)
- **l4_lb**: Load balancer + client + 4 backends (:80, :443)
- **l7_proxy**: L7 proxy + client + api-backend + static-backend (:80, :443, :8080)
- **full_stack**: Complete: clients → VPN gateway → LB → proxy → backends

### When to Use Which
- VPN-only tests (tunnel, encryption, leak, kill switch) → `vpn_basic`
- L4 load balancing tests (distribution, health checks, NAT) → `l4_lb`
- L7/WAF/TLS tests (routing, TLS termination, WAF rules) → `l7_proxy`
- Cross-feature tests, integration tests → `full_stack`
- Performance tests → topology matching the feature under test
- If in doubt → `full_stack` (has all components)
