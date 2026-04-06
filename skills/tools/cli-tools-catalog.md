---
name: cli-tools-catalog
description: Catalog of CLI tools available for network testing, their capabilities, and when to recommend them for new integrations
domain: tools
applies_to: [gap_analysis, api_enhance]
priority: 1
tags: [tools, catalog, integration, cli]
---

## Network Testing CLI Tools Catalog

Use this catalog to identify which CLI tools are needed for test capabilities
that the existing helper modules don't cover.

### HTTP/Web Testing
- **wget**: Recursive download, cookie persistence, retry logic, bandwidth limiting, mirror sites. Use when testing HTTP download behavior, cookie handling, redirect chains, or content mirroring.
- **curl**: HTTP requests with headers, auth, cookies, TLS options. Already partially wrapped in traffic.py.
- **ab** (Apache Bench): HTTP load testing with concurrency control. Use for simple RPS benchmarking.
- **wrk**: Modern HTTP benchmarking with Lua scripting. Use for complex load patterns, custom request generation.
- **hey**: Simple HTTP load generator. Use for quick latency distribution testing.
- **siege**: HTTP regression testing and benchmarking. Use for prolonged load testing with session support.

### DNS Testing
- **dig**: DNS query tool with full record type support (A, AAAA, MX, TXT, SRV, DNSSEC). Use for DNS resolution validation, DNSSEC verification, TTL checking.
- **nslookup**: Basic DNS lookup. Use for simple resolution checks.
- **dnstracer**: Trace DNS delegation chain. Use for debugging DNS delegation issues.

### Network Diagnostics
- **mtr**: Combined traceroute + ping with statistics. Use for path analysis, hop-by-hop latency measurement.
- **traceroute**: Path discovery. Use for verifying routing paths through topology.
- **ss**: Socket statistics. Use for checking connection states, socket buffer sizes, TCP retransmissions.
- **conntrack**: Connection tracking table inspection. Use for NAT/stateful firewall testing.
- **ethtool**: NIC statistics and configuration. Use for checking link state, speed, offload settings.

### Traffic Control
- **tc** (traffic control): Network emulation — add latency, jitter, packet loss, bandwidth limits. Use for testing product behavior under degraded network conditions.
- **netem**: (via tc qdisc) Network emulator for delay, loss, duplication, reordering.

### TLS/Crypto
- **openssl s_client**: TLS connection testing, certificate inspection, cipher negotiation. Use for targeted TLS debugging beyond what testssl.sh covers.
- **certutil**: Certificate management. Use for testing certificate stores.

### Connectivity
- **socat**: Bidirectional data relay (TCP, UDP, Unix sockets, TLS). Use for protocol bridging, proxy testing, TLS tunneling.
- **netcat (nc)**: TCP/UDP connection utility. Use for basic port testing, banner grabbing, simple data transfer.
- **hping3**: TCP/IP packet assembler. Already referenced but not fully wrapped.

### Packet Manipulation
- **scapy**: Packet crafting (Python). Already wrapped in traffic.py.
- **tcpreplay**: Replay pcap files. Use for replaying captured traffic patterns.
- **nping**: Packet generation with response analysis. Use for custom protocol testing.

### Module Placement Guide
When creating a new module, follow this placement logic:
- HTTP-focused tools (wget, ab, wrk, hey) → `src/networking/http_client.py`
- DNS tools (dig, nslookup) → `src/networking/dns.py`
- Diagnostic tools (mtr, ss, conntrack) → `src/networking/diagnostics.py`
- Traffic control (tc, netem) → `src/networking/traffic_control.py`
- TLS tools (openssl s_client) → extend `src/networking/protocol.py`
- Connectivity (socat, nc) → `src/networking/connectivity.py`
