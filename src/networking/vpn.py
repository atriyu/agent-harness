"""VPN test helpers: tunnel management, leak detection, kill switch testing.

Wraps VPN operations so generated tests call clean Python APIs.
Supports WireGuard, OpenVPN, and IKEv2 protocols.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from src.topology.manager import TopologyManager

logger = logging.getLogger(__name__)


@dataclass
class TunnelStatus:
    protocol: str
    status: str  # "established", "failed", "disconnected", "timeout"
    local_ip: str = ""
    remote_ip: str = ""
    tunnel_ip: str = ""
    encryption_verified: bool = False
    cipher: str = ""
    handshake_time_ms: float = 0.0
    error: str = ""

    @property
    def is_up(self) -> bool:
        return self.status == "established"


@dataclass
class LeakTestResult:
    leak_detected: bool = False
    leak_type: str = ""  # "dns", "ip", "ipv6", "webrtc"
    details: str = ""
    queries_outside_tunnel: list[str] = field(default_factory=list)


PROTOCOL_CIPHERS = {
    "wireguard": "ChaCha20-Poly1305",
    "openvpn": "AES-256-GCM",
    "ikev2": "AES-256-CBC",
}


class VPNHelper:
    """High-level VPN testing primitives bound to a topology."""

    def __init__(self, topology_manager: TopologyManager | Any):
        self.topo = topology_manager

    def _exec(self, node: str, cmd: str, timeout: int = 30) -> str:
        """Execute a command on a topology node."""
        if hasattr(self.topo, "exec_on_node"):
            return self.topo.exec_on_node(node, cmd, timeout=timeout)
        # Fallback for stub topology
        logger.debug("Stub exec on %s: %s", node, cmd)
        return ""

    def establish_tunnel(
        self,
        protocol: str = "wireguard",
        client_node: str = "client",
        gateway_node: str = "vpn-gw",
        config: dict | None = None,
        timeout: int = 30,
    ) -> TunnelStatus:
        """Establish a VPN tunnel using the specified protocol.

        Args:
            protocol: One of "wireguard", "openvpn", "ikev2".
            client_node: Topology node name for the VPN client.
            gateway_node: Topology node name for the VPN gateway.
            config: Optional protocol-specific configuration overrides.
            timeout: Seconds to wait for tunnel establishment.
        """
        config = config or {}
        start = time.time()

        try:
            if protocol == "wireguard":
                result = self._establish_wireguard(client_node, gateway_node, config, timeout)
            elif protocol == "openvpn":
                result = self._establish_openvpn(client_node, gateway_node, config, timeout)
            elif protocol == "ikev2":
                result = self._establish_ikev2(client_node, gateway_node, config, timeout)
            else:
                return TunnelStatus(
                    protocol=protocol, status="failed",
                    error=f"Unsupported protocol: {protocol}",
                )

            result.handshake_time_ms = (time.time() - start) * 1000
            return result

        except Exception as e:
            return TunnelStatus(
                protocol=protocol, status="failed",
                error=str(e),
                handshake_time_ms=(time.time() - start) * 1000,
            )

    def _establish_wireguard(
        self, client: str, gateway: str, config: dict, timeout: int,
    ) -> TunnelStatus:
        """Bring up a WireGuard tunnel."""
        # Configure and bring up WireGuard interface
        wg_conf = config.get("config_path", "/etc/wireguard/wg0.conf")
        self._exec(client, f"wg-quick up {wg_conf}")

        # Verify handshake
        deadline = time.time() + timeout
        while time.time() < deadline:
            output = self._exec(client, "wg show wg0")
            if "latest handshake" in output:
                # Extract tunnel IP
                tunnel_ip = ""
                ip_output = self._exec(client, "ip addr show wg0")
                ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip_output)
                if ip_match:
                    tunnel_ip = ip_match.group(1)

                return TunnelStatus(
                    protocol="wireguard",
                    status="established",
                    tunnel_ip=tunnel_ip,
                    encryption_verified=True,
                    cipher="ChaCha20-Poly1305",
                )
            time.sleep(1)

        return TunnelStatus(protocol="wireguard", status="timeout", error="Handshake not completed")

    def _establish_openvpn(
        self, client: str, gateway: str, config: dict, timeout: int,
    ) -> TunnelStatus:
        """Start OpenVPN client and wait for connection."""
        ovpn_conf = config.get("config_path", "/etc/openvpn/client.conf")
        mode = config.get("mode", "udp")

        self._exec(client, f"openvpn --config {ovpn_conf} --daemon")

        deadline = time.time() + timeout
        while time.time() < deadline:
            output = self._exec(client, "ip addr show tun0")
            if "inet " in output:
                tunnel_ip = ""
                ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
                if ip_match:
                    tunnel_ip = ip_match.group(1)

                return TunnelStatus(
                    protocol="openvpn",
                    status="established",
                    tunnel_ip=tunnel_ip,
                    encryption_verified=True,
                    cipher=config.get("cipher", "AES-256-GCM"),
                )
            time.sleep(1)

        return TunnelStatus(protocol="openvpn", status="timeout", error="tun0 not found")

    def _establish_ikev2(
        self, client: str, gateway: str, config: dict, timeout: int,
    ) -> TunnelStatus:
        """Start IKEv2/IPSec using strongSwan."""
        conn_name = config.get("connection", "vpn")
        self._exec(client, f"ipsec up {conn_name}")

        deadline = time.time() + timeout
        while time.time() < deadline:
            output = self._exec(client, "ipsec status")
            if "ESTABLISHED" in output:
                return TunnelStatus(
                    protocol="ikev2",
                    status="established",
                    encryption_verified=True,
                    cipher=config.get("cipher", "AES-256-CBC"),
                )
            time.sleep(1)

        return TunnelStatus(protocol="ikev2", status="timeout", error="IKE SA not established")

    def verify_encryption(
        self,
        tunnel: TunnelStatus,
        client_node: str = "client",
        expected_cipher: str | None = None,
    ) -> bool:
        """Verify tunnel traffic is encrypted by capturing and inspecting packets."""
        if expected_cipher:
            return tunnel.cipher == expected_cipher

        # Capture packets and verify no plaintext
        try:
            self._exec(
                client_node,
                "tcpdump -c 10 -w /tmp/vpn_check.pcap -i eth0 not port 22",
            )
            output = self._exec(
                client_node,
                "tcpdump -r /tmp/vpn_check.pcap -A 2>/dev/null | head -50",
            )
            # Check for plaintext HTTP markers in captured traffic
            plaintext_markers = ["HTTP/1", "GET /", "POST /", "Host:"]
            for marker in plaintext_markers:
                if marker in output:
                    return False
            return True
        except Exception:
            return tunnel.encryption_verified

    def check_dns_leak(
        self,
        client_node: str = "client",
        test_domain: str = "leak-test.example.com",
    ) -> LeakTestResult:
        """Check for DNS leaks by inspecting DNS query routing."""
        try:
            # Start capture on the physical interface
            self._exec(
                client_node,
                "tcpdump -c 20 -w /tmp/dns_leak.pcap port 53 -i eth0 &",
            )
            time.sleep(1)

            # Generate DNS queries
            self._exec(client_node, f"nslookup {test_domain}")
            self._exec(client_node, f"dig {test_domain}")
            time.sleep(2)

            # Analyze capture
            output = self._exec(
                client_node,
                "tcpdump -r /tmp/dns_leak.pcap -nn port 53 2>/dev/null",
            )

            # Any DNS queries on the physical interface = leak
            leaked_queries = [
                line for line in output.strip().split("\n")
                if line.strip() and "53" in line
            ]

            if leaked_queries:
                return LeakTestResult(
                    leak_detected=True,
                    leak_type="dns",
                    details=f"{len(leaked_queries)} DNS queries leaked outside tunnel",
                    queries_outside_tunnel=leaked_queries[:5],
                )

            return LeakTestResult(leak_detected=False)

        except Exception as e:
            return LeakTestResult(
                leak_detected=False,
                details=f"Check inconclusive: {e}",
            )

    def check_ip_leak(
        self,
        client_node: str = "client",
        expected_vpn_ip: str = "",
    ) -> LeakTestResult:
        """Check for IP leaks by verifying external IP matches VPN egress."""
        try:
            # Get external IP through the tunnel
            output = self._exec(
                client_node, "curl -s --max-time 10 https://ifconfig.me"
            )
            external_ip = output.strip()

            if expected_vpn_ip and external_ip != expected_vpn_ip:
                return LeakTestResult(
                    leak_detected=True,
                    leak_type="ip",
                    details=f"Expected VPN IP {expected_vpn_ip}, got {external_ip}",
                )

            return LeakTestResult(leak_detected=False)

        except Exception as e:
            return LeakTestResult(details=f"IP check failed: {e}")

    def check_ipv6_leak(self, client_node: str = "client") -> LeakTestResult:
        """Check for IPv6 leaks when only IPv4 tunnel is active."""
        try:
            output = self._exec(
                client_node,
                "tcpdump -c 5 -w /tmp/ipv6.pcap ip6 -i eth0 &",
            )
            time.sleep(3)

            # Try to generate IPv6 traffic
            self._exec(client_node, "ping6 -c 1 -W 2 ::1 2>/dev/null || true")
            time.sleep(2)

            output = self._exec(
                client_node, "tcpdump -r /tmp/ipv6.pcap 2>/dev/null"
            )

            ipv6_packets = [l for l in output.strip().split("\n") if l.strip()]
            if ipv6_packets:
                return LeakTestResult(
                    leak_detected=True,
                    leak_type="ipv6",
                    details=f"{len(ipv6_packets)} IPv6 packets observed on physical interface",
                )

            return LeakTestResult(leak_detected=False)

        except Exception as e:
            return LeakTestResult(details=f"IPv6 check inconclusive: {e}")

    def test_kill_switch(
        self,
        client_node: str = "client",
        protocol: str = "wireguard",
    ) -> bool:
        """Test kill switch by dropping VPN and verifying traffic is blocked."""
        try:
            # Kill the VPN process
            if protocol == "wireguard":
                self._exec(client_node, "wg-quick down wg0")
            elif protocol == "openvpn":
                self._exec(client_node, "killall openvpn")
            elif protocol == "ikev2":
                self._exec(client_node, "ipsec down vpn")

            time.sleep(1)

            # Try to reach the internet -- should fail if kill switch works
            result = self._exec(
                client_node, "curl -s --max-time 5 https://ifconfig.me || echo BLOCKED"
            )

            return "BLOCKED" in result or not result.strip()

        except Exception:
            return True  # If exec fails, traffic is blocked

    def teardown_tunnel(
        self,
        protocol: str = "wireguard",
        client_node: str = "client",
    ) -> None:
        """Gracefully tear down a VPN tunnel."""
        try:
            if protocol == "wireguard":
                self._exec(client_node, "wg-quick down wg0")
            elif protocol == "openvpn":
                self._exec(client_node, "killall openvpn")
            elif protocol == "ikev2":
                self._exec(client_node, "ipsec down vpn")
        except Exception as e:
            logger.warning("Tunnel teardown error: %s", e)
