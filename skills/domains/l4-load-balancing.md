---
name: l4-load-balancing
description: Layer 4 load balancing test patterns including algorithms, NAT, connection tracking, and health checks
domain: l4
applies_to: [plan, codegen, triage]
priority: 1
tags: [l4, tcp, udp, load-balancing, nat, snat, dnat, connection-tracking]
---

## L4 Load Balancing Test Patterns

### Distribution Algorithms
- **Round-robin**: Traffic must distribute evenly across N backends (within 5% variance)
- **Least-connections**: New connections must route to the backend with fewest active connections
- Test with varying backend counts (2, 4, 8)
- Verify distribution accuracy with 1000+ requests

### Health Checks
- TCP connect health check: backend marked down within 10 seconds of failure
- HTTP GET health check: verify status code and response body matching
- Test health check intervals (default 5s) and thresholds (3 failures = down)
- Verify traffic stops flowing to failed backends immediately

### Connection Draining
- Remove a backend: existing connections must complete within drain period (default 30s)
- New connections must not route to draining backend
- Verify graceful completion of in-flight requests

### NAT
- **SNAT**: Verify source port mapping preserved for 10,000 concurrent connections
- **DNAT**: Verify port forwarding routes correctly to internal servers
- Test SNAT port exhaustion: what happens at maximum concurrent connections?
- Verify NAT table cleanup after connection close

### Connection Tracking
- Connection table must handle 100,000 simultaneous entries
- Verify stateful firewall rules respect connection state (NEW, ESTABLISHED, RELATED)
- Test connection table overflow behavior

### Mixed Traffic
- Test with simultaneous TCP and UDP traffic
- Test with mixed packet sizes (64B, 512B, 1500B, 9000B jumbo)
- Verify DSCP markings preserved through load balancer
