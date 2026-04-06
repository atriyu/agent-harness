---
name: failover-testing
description: High availability and failover test patterns including active-passive, session persistence, and split-brain scenarios
domain: ha
applies_to: [plan, codegen]
priority: 3
tags: [ha, failover, redundancy, session-persistence, split-brain]
---

## Failover & HA Testing Patterns

### Active-Passive Failover
- Failover time: less than 3 seconds from primary failure to standby takeover
- Measure by: kill primary process, time until standby serves traffic
- Verify VIP (virtual IP) moves to standby correctly
- Test failover triggers: process crash, network partition, health check failure

### Session State Replication
- Active sessions must survive failover
- Verify: establish VPN tunnel → kill primary → verify tunnel remains up on standby
- Verify: establish HTTP session → kill primary → verify session cookie still valid
- Measure state replication lag (should be < 1 second)

### Failback
- Automatic failback when primary recovers
- Verify no traffic disruption during failback
- Verify state re-synchronization after failback
- Test rapid failover/failback cycling (flapping)

### Split-Brain Prevention
- Simulate network partition between primary and standby
- Verify only ONE node serves traffic (no dual-active)
- Test with fencing mechanisms (STONITH)
- Verify recovery after partition heals

### Under-Load Failover
- Run iperf3 at sustained load → trigger failover → verify:
  - Existing connections continue (or reconnect within 3s)
  - New connections succeed immediately after failover
  - No packet loss > 0.1% during transition
