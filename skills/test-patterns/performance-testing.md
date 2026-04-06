---
name: performance-testing
description: Performance test patterns for throughput, latency, scalability with iperf3 baselines and packet size variations
domain: performance
applies_to: [plan, codegen]
priority: 2
tags: [performance, throughput, latency, jitter, iperf3, scalability]
---

## Performance Testing Patterns

### Throughput Baselines
- VPN tunnel: minimum 1 Gbps with encryption active
- L4 load balancer: minimum 10 Gbps aggregate
- L7 proxy: minimum 100,000 HTTP requests per second
- Measure with iperf3 for raw throughput, wrk/ab for HTTP RPS

### Latency Measurement
- Measure at p50, p95, p99 percentiles (not just average)
- VPN added latency: less than 2ms
- L4 forwarding: less than 500 microseconds
- L7 proxy with TLS: less than 5ms at p99
- Use repeated measurements (minimum 10 runs) for statistical validity

### Packet Size Variations
- Test with standard sizes: 64B, 512B, 1500B (MTU), 9000B (jumbo frames)
- Verify no fragmentation issues at each size
- Measure throughput degradation with small packets

### Scalability
- Connection count: 100, 1000, 10000, 100000 concurrent
- Verify linear scaling behavior
- Identify the knee point where performance degrades
- Test connection establishment rate (connections/second)

### Sustained Load
- Run throughput tests for extended duration (5 min minimum)
- Monitor for memory leaks, CPU saturation, connection table growth
- Verify consistent performance (no degradation over time)

### Tool Usage
- iperf3: `iperf3 -c <server> -t <duration> -P <parallel> --json`
  - TCP: add `-b` for bandwidth target
  - UDP: add `-u -b <rate>` for UDP testing
- Parse JSON output for bits_per_second, jitter_ms, lost_percent
