---
name: vpn-protocols
description: VPN protocol test expertise for WireGuard, OpenVPN, and IKEv2 including tunnel lifecycle, encryption, and leak prevention
domain: vpn
applies_to: [plan, codegen, triage]
priority: 1
tags: [vpn, wireguard, openvpn, ikev2, tunnel, encryption]
---

## VPN Protocol Testing Patterns

### WireGuard
- Tunnel establishment: handshake must complete within 5 seconds
- Cipher: ChaCha20-Poly1305 (verify in packet capture)
- Test with and without persistent keepalive
- Key rotation: verify rekeying under sustained load
- Interface: typically `wg0`, verify IP assignment via `ip addr show wg0`

### OpenVPN
- Test both UDP and TCP modes
- Cipher: AES-256-GCM (configurable)
- Interface: typically `tun0`
- Test with `--daemon` mode and verify tun interface comes up
- Verify graceful fallback from UDP to TCP when UDP is blocked

### IKEv2/IPSec (strongSwan)
- Cipher: AES-256-CBC with SHA-256 HMAC
- Verify IKE SA establishment via `ipsec status`
- Test with multiple concurrent SAs
- Perfect Forward Secrecy (PFS) must be enabled on all protocols

### Cross-Protocol Tests
- Test graceful fallback: WireGuard → OpenVPN if handshake fails
- Verify no traffic leaks during protocol switch
- Compare performance (throughput, latency) across protocols
- Test tunnel stability over extended periods (30+ minutes)

### Leak Prevention (ALL protocols)
- DNS leak: capture port 53 on physical interface during active tunnel; zero queries expected
- IP leak: `curl ifconfig.me` must return VPN egress IP, not client real IP
- IPv6 leak: block IPv6 on physical interface when only IPv4 tunnel is active
- WebRTC leak: verify no local IP disclosure via WebRTC APIs

### Kill Switch
- Drop VPN process, verify ALL internet traffic blocked within 500ms
- Local network access must remain available during kill switch
- Kill switch must engage on: process crash, network change, server unreachable
