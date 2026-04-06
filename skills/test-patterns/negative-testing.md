---
name: negative-testing
description: Negative and boundary test patterns including error injection, malformed input, and resource exhaustion
domain: testing
applies_to: [plan]
priority: 3
tags: [negative, boundary, error-injection, malformed, exhaustion]
---

## Negative & Boundary Testing Patterns

### Error Injection
- Send malformed packets (truncated headers, invalid checksums)
- Send oversized packets (> MTU without fragmentation)
- Send packets with invalid protocol versions
- Inject network errors: packet loss (1%, 5%, 10%), latency (50ms, 200ms, 1s), jitter

### Boundary Conditions
- Zero-length payloads
- Maximum-length payloads (64KB TCP, 65535B UDP)
- Connection at exact limit (e.g., connection table at 100,000)
- Timeout at exact boundary (connect at T-1ms, T, T+1ms)

### Resource Exhaustion
- File descriptor exhaustion: open connections until FD limit
- Memory pressure: large number of concurrent sessions with state
- CPU saturation: high packet rate with complex processing (WAF rules)
- Connection table overflow: exceed maximum entries

### Invalid Input
- Invalid IP addresses in headers
- Wrong protocol on expected port (HTTP on SSH port)
- Expired/invalid TLS certificates
- Wrong authentication credentials (VPN, API keys)
- Unsupported cipher suite negotiation

### Recovery After Error
- Verify service recovers after resource exhaustion
- Verify new connections accepted after overload subsides
- Verify no persistent state corruption after error conditions
