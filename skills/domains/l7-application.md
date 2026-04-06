---
name: l7-application
description: Layer 7 application service test patterns including TLS termination, content routing, WAF, and session affinity
domain: l7
applies_to: [plan, codegen, triage]
priority: 1
tags: [l7, tls, ssl, waf, routing, proxy, session-affinity, sni]
---

## L7 Application Service Test Patterns

### TLS Termination
- Support TLS 1.2 and TLS 1.3
- Reject TLS 1.0 and TLS 1.1 connections
- SNI-based certificate selection: correct cert served based on hostname
- OCSP stapling: verify stapled response in TLS handshake
- TLS handshake must complete within 50ms
- Verify no plaintext between proxy and client

### Content-Based Routing
- URL path prefix: `/api/*` → API backend pool, `/static/*` → CDN pool
- Host header matching: `api.example.com` vs `www.example.com`
- Cookie-based session affinity: same session cookie → same backend for 30 minutes
- Header-based routing: custom `X-Route` header directs to specific pool
- Test with overlapping rules (most specific wins)
- Verify 404 for routes that match no backend

### Web Application Firewall (WAF)
- SQL injection: payloads in query params, body, headers must return 403
  - Test: `' OR 1=1 --`, `UNION SELECT`, `; DROP TABLE`
- XSS prevention: script tags in request body must be blocked
  - Test: `<script>alert(1)</script>`, `javascript:`, event handlers
- Rate limiting: activate after 100 requests/minute per IP
  - Verify 429 response after threshold
  - Verify counter reset after window
- Test WAF bypass attempts (encoding, chunked transfer, case variations)

### Session Persistence
- Cookie-based affinity must maintain for configured duration (30 min default)
- Verify affinity breaks correctly after timeout
- Test affinity with backend failover (redirect to new backend)
- Verify session data survives backend restart

### Performance
- L7 proxy: minimum 100,000 HTTP requests per second
- Latency (including TLS): less than 5ms at p99
- Test with concurrent connections (100, 1000, 10000)
