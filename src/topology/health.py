"""Topology health checks: verify all nodes are reachable and services are running."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field

from src.topology.inventory import TopologyInventory, NodeInventoryEntry
from src.topology.manager import TopologyManager

logger = logging.getLogger(__name__)


@dataclass
class NodeHealthStatus:
    name: str
    reachable: bool = False
    ssh_available: bool = False
    services_up: list[str] = field(default_factory=list)
    services_down: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class TopologyHealthReport:
    topology_name: str
    all_healthy: bool = False
    node_statuses: dict[str, NodeHealthStatus] = field(default_factory=dict)
    check_duration_seconds: float = 0.0


def _ping_check(ip: str, timeout: int = 5) -> tuple[bool, float]:
    """Ping a node and return (reachable, latency_ms)."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        if result.returncode == 0:
            # Parse latency from ping output
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    time_part = line.split("time=")[1].split()[0]
                    return True, float(time_part)
            return True, 0.0
        return False, 0.0
    except (subprocess.TimeoutExpired, Exception):
        return False, 0.0


def _tcp_check(ip: str, port: int, timeout: int = 5) -> bool:
    """Check if a TCP port is open."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def check_node_health(
    node: NodeInventoryEntry,
    check_ssh: bool = True,
    additional_ports: list[int] | None = None,
) -> NodeHealthStatus:
    """Check health of a single node."""
    status = NodeHealthStatus(name=node.name)

    if not node.ipv4:
        status.error = "No IPv4 address assigned"
        return status

    # Ping check
    reachable, latency = _ping_check(node.ipv4)
    status.reachable = reachable
    status.latency_ms = latency

    if not reachable:
        status.error = f"Node unreachable at {node.ipv4}"
        return status

    # SSH check
    if check_ssh:
        if _tcp_check(node.ipv4, node.ssh_port):
            status.ssh_available = True
            status.services_up.append(f"ssh:{node.ssh_port}")
        else:
            status.services_down.append(f"ssh:{node.ssh_port}")

    # Additional port checks
    for port in (additional_ports or []):
        if _tcp_check(node.ipv4, port):
            status.services_up.append(f"tcp:{port}")
        else:
            status.services_down.append(f"tcp:{port}")

    return status


def check_topology_health(
    inventory: TopologyInventory,
    check_ssh: bool = True,
    role_ports: dict[str, list[int]] | None = None,
) -> TopologyHealthReport:
    """Check health of all nodes in a topology.

    Args:
        inventory: The topology inventory to check.
        check_ssh: Whether to check SSH availability.
        role_ports: Additional ports to check per role, e.g. {"proxy": [80, 443]}.
    """
    role_ports = role_ports or {}
    start = time.time()
    report = TopologyHealthReport(topology_name=inventory.topology_name)

    for name, node in inventory.nodes.items():
        extra_ports = role_ports.get(node.role, [])
        status = check_node_health(node, check_ssh=check_ssh, additional_ports=extra_ports)
        report.node_statuses[name] = status

    report.check_duration_seconds = time.time() - start
    report.all_healthy = all(
        s.reachable and not s.services_down
        for s in report.node_statuses.values()
    )

    return report


def wait_for_topology_healthy(
    inventory: TopologyInventory,
    timeout_seconds: int = 120,
    poll_interval: int = 5,
    role_ports: dict[str, list[int]] | None = None,
) -> TopologyHealthReport:
    """Poll until all nodes are healthy or timeout is reached."""
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        report = check_topology_health(inventory, role_ports=role_ports)
        if report.all_healthy:
            logger.info(
                "Topology '%s' healthy in %.1fs",
                inventory.topology_name, report.check_duration_seconds,
            )
            return report

        unhealthy = [
            n for n, s in report.node_statuses.items()
            if not s.reachable or s.services_down
        ]
        logger.info(
            "Waiting for topology health... unhealthy: %s (%.0fs remaining)",
            unhealthy, deadline - time.time(),
        )
        time.sleep(poll_interval)

    # Final check
    report = check_topology_health(inventory, role_ports=role_ports)
    if not report.all_healthy:
        unhealthy_details = {
            n: s.error or f"services_down={s.services_down}"
            for n, s in report.node_statuses.items()
            if not s.reachable or s.services_down
        }
        logger.error("Topology health check timed out. Unhealthy: %s", unhealthy_details)
    return report
