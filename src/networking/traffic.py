"""Traffic generation helpers: iperf3, scapy, HTTP, bulk connections.

Provides clean Python APIs for traffic generation that generated tests can call.
All operations execute on topology nodes via the topology manager.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from src.topology.manager import TopologyManager

logger = logging.getLogger(__name__)


@dataclass
class IperfResult:
    bandwidth_mbps: float = 0.0
    bandwidth_gbps: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    retransmits: int = 0
    duration_seconds: float = 0.0
    protocol: str = "tcp"
    bytes_transferred: int = 0
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error and self.bandwidth_mbps > 0


@dataclass
class ConnectionResult:
    total_attempted: int = 0
    successful: int = 0
    failed: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    error: str = ""


@dataclass
class HttpResponse:
    status_code: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    latency_ms: float = 0.0
    error: str = ""


class TrafficGenerator:
    """Traffic generation primitives bound to a topology."""

    def __init__(self, topology_manager: TopologyManager | Any):
        self.topo = topology_manager

    def _exec(self, node: str, cmd: str, timeout: int = 60) -> str:
        if hasattr(self.topo, "exec_on_node"):
            return self.topo.exec_on_node(node, cmd, timeout=timeout)
        logger.debug("Stub exec on %s: %s", node, cmd)
        return ""

    def iperf3(
        self,
        src: str = "client",
        dst: str = "server",
        dst_ip: str = "",
        protocol: str = "tcp",
        duration: int = 10,
        bandwidth: str | None = None,
        parallel: int = 1,
        reverse: bool = False,
    ) -> IperfResult:
        """Run an iperf3 test between two topology nodes.

        Args:
            src: Source node name (runs iperf3 client).
            dst: Destination node name (must have iperf3 server running).
            dst_ip: Explicit destination IP (overrides topology lookup).
            protocol: "tcp" or "udp".
            duration: Test duration in seconds.
            bandwidth: Target bandwidth (e.g., "1G", "100M"). None = unlimited.
            parallel: Number of parallel streams.
            reverse: If True, server sends to client.
        """
        # Resolve destination IP
        if not dst_ip and hasattr(self.topo, "get_node_address"):
            try:
                dst_ip = self.topo.get_node_address(dst)
            except (KeyError, RuntimeError):
                dst_ip = dst

        # Build iperf3 command
        cmd_parts = [
            "iperf3", "-c", dst_ip,
            "-t", str(duration),
            "-P", str(parallel),
            "--json",
        ]
        if protocol == "udp":
            cmd_parts.append("-u")
        if bandwidth:
            cmd_parts.extend(["-b", bandwidth])
        if reverse:
            cmd_parts.append("-R")

        cmd = " ".join(cmd_parts)

        try:
            output = self._exec(src, cmd, timeout=duration + 30)
            return self._parse_iperf_json(output, protocol)
        except Exception as e:
            return IperfResult(error=str(e), protocol=protocol, duration_seconds=float(duration))

    def _parse_iperf_json(self, output: str, protocol: str) -> IperfResult:
        """Parse iperf3 JSON output into our result model."""
        try:
            data = json.loads(output)

            if "error" in data:
                return IperfResult(error=data["error"], protocol=protocol)

            end = data.get("end", {})
            duration = end.get("sum_sent", {}).get("seconds", 0) or end.get("sum", {}).get("seconds", 0)

            if protocol == "udp":
                sum_data = end.get("sum", {})
                return IperfResult(
                    bandwidth_mbps=sum_data.get("bits_per_second", 0) / 1_000_000,
                    bandwidth_gbps=sum_data.get("bits_per_second", 0) / 1_000_000_000,
                    jitter_ms=sum_data.get("jitter_ms", 0),
                    packet_loss_pct=sum_data.get("lost_percent", 0),
                    duration_seconds=duration,
                    protocol="udp",
                    bytes_transferred=sum_data.get("bytes", 0),
                )
            else:
                sent = end.get("sum_sent", {})
                return IperfResult(
                    bandwidth_mbps=sent.get("bits_per_second", 0) / 1_000_000,
                    bandwidth_gbps=sent.get("bits_per_second", 0) / 1_000_000_000,
                    retransmits=sent.get("retransmits", 0),
                    duration_seconds=duration,
                    protocol="tcp",
                    bytes_transferred=sent.get("bytes", 0),
                )

        except (json.JSONDecodeError, KeyError) as e:
            return IperfResult(error=f"Failed to parse iperf3 output: {e}", protocol=protocol)

    def scapy_send(
        self,
        src: str,
        packet_definition: str,
        count: int = 1,
        inter: float = 0.1,
    ) -> int:
        """Send crafted packets from a source node using scapy.

        Args:
            src: Source node name.
            packet_definition: Scapy packet expression, e.g. 'IP(dst="10.0.0.1")/TCP(dport=80)'
            count: Number of packets to send.
            inter: Inter-packet interval in seconds.

        Returns:
            Number of packets sent.
        """
        cmd = (
            f"python3 -c \""
            f"from scapy.all import *; "
            f"send({packet_definition}, count={count}, inter={inter}, verbose=0); "
            f"print('SENT:{count}')"
            f"\""
        )

        try:
            output = self._exec(src, cmd, timeout=count * inter + 30)
            match = re.search(r"SENT:(\d+)", output)
            return int(match.group(1)) if match else 0
        except Exception as e:
            logger.warning("scapy_send failed: %s", e)
            return 0

    def http_request(
        self,
        src: str,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str = "",
        timeout: int = 10,
    ) -> HttpResponse:
        """Make an HTTP request from a topology node using curl."""
        cmd_parts = [
            "curl", "-s", "-o", "/tmp/curl_body",
            "-w", '"%{http_code}|%{time_total}"',
            "-X", method,
            "--max-time", str(timeout),
            "-D", "/tmp/curl_headers",
        ]

        for key, val in (headers or {}).items():
            cmd_parts.extend(["-H", f'"{key}: {val}"'])

        if body:
            cmd_parts.extend(["-d", f"'{body}'"])

        cmd_parts.append(f'"{url}"')
        cmd = " ".join(cmd_parts)

        try:
            output = self._exec(src, cmd, timeout=timeout + 10)
            parts = output.strip().strip('"').split("|")

            status_code = int(parts[0]) if parts[0].isdigit() else 0
            latency_ms = float(parts[1]) * 1000 if len(parts) > 1 else 0

            # Read response body and headers
            resp_body = self._exec(src, "cat /tmp/curl_body 2>/dev/null || true")
            resp_headers_raw = self._exec(src, "cat /tmp/curl_headers 2>/dev/null || true")

            resp_headers = {}
            for line in resp_headers_raw.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    resp_headers[k.strip()] = v.strip()

            return HttpResponse(
                status_code=status_code,
                headers=resp_headers,
                body=resp_body[:5000],
                latency_ms=latency_ms,
            )

        except Exception as e:
            return HttpResponse(error=str(e))

    def bulk_connections(
        self,
        src: str = "client",
        dst: str = "server",
        dst_ip: str = "",
        count: int = 100,
        port: int = 80,
        protocol: str = "tcp",
    ) -> ConnectionResult:
        """Open many connections for scalability testing.

        Uses a Python script on the source node to rapidly open/close connections.
        """
        if not dst_ip and hasattr(self.topo, "get_node_address"):
            try:
                dst_ip = self.topo.get_node_address(dst)
            except (KeyError, RuntimeError):
                dst_ip = dst

        script = (
            f"python3 -c \""
            f"import socket, time, json; "
            f"results = {{'ok': 0, 'fail': 0, 'latencies': []}}; "
            f"for i in range({count}): "
            f"  s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); "
            f"  s.settimeout(5); "
            f"  t0 = time.time(); "
            f"  try: s.connect(('{dst_ip}', {port})); results['ok'] += 1; "
            f"  results['latencies'].append((time.time() - t0) * 1000); "
            f"  except: results['fail'] += 1; "
            f"  finally: s.close(); "
            f"print(json.dumps(results))"
            f"\""
        )

        try:
            output = self._exec(src, script, timeout=count + 30)
            data = json.loads(output.strip().split("\n")[-1])

            latencies = data.get("latencies", [])
            return ConnectionResult(
                total_attempted=count,
                successful=data.get("ok", 0),
                failed=data.get("fail", 0),
                avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
                max_latency_ms=max(latencies) if latencies else 0,
                min_latency_ms=min(latencies) if latencies else 0,
            )

        except Exception as e:
            return ConnectionResult(
                total_attempted=count, error=str(e),
            )
