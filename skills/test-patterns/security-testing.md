---
name: security-testing
description: Security test patterns covering encryption standards, cipher validation, PFS, vulnerability scanning, and access control
domain: security
applies_to: [plan, codegen, extract]
priority: 2
tags: [security, encryption, cipher, pfs, vulnerability, owasp]
---

## Security Testing Patterns

### Encryption Standards Verification
- WireGuard: ChaCha20-Poly1305
- OpenVPN: AES-256-GCM
- IKEv2: AES-256-CBC with SHA-256 HMAC
- RSA/DH keys: minimum 2,048-bit
- Verify via packet capture: no plaintext markers (HTTP/1, GET, POST, Host:) in encrypted traffic

### Perfect Forward Secrecy (PFS)
- Verify PFS enabled on all TLS connections (testssl.sh -f flag)
- Key rotation must occur every 60 minutes
- Capture of past traffic must not be decryptable with current keys

### Certificate Validation
- Valid certificates accepted
- Expired certificates rejected
- Self-signed certificates rejected (unless explicitly trusted)
- Hostname mismatch rejected
- Revoked certificates checked via OCSP

### Port Scanning
- Only expected ports should be open (nmap scan)
- No unnecessary services exposed
- Management interfaces not accessible from untrusted networks

### Cipher Suite Validation
- Strong ciphers only: TLS_AES_256_GCM_SHA384, TLS_CHACHA20_POLY1305_SHA256
- Weak ciphers must be rejected: RC4, DES, 3DES, NULL
- Verify cipher preference order (server preference)

### Rate Limiting & DDoS
- Per-IP rate limiting enforced
- Per-endpoint rate limiting for sensitive APIs
- Connection flood protection (SYN flood, slowloris)
