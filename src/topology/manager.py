"""Containerlab topology lifecycle management: deploy, inspect, destroy.

Wraps the `containerlab` CLI to manage Docker-based network topologies
for test execution.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TopologyNode:
    name: str
    kind: str
    image: str
    container_id: str = ""
    ipv4_address: str = ""
    ipv6_address: str = ""
    state: str = "unknown"
    interfaces: dict[str, str] = field(default_factory=dict)


@dataclass
class TopologyInfo:
    name: str
    topology_file: str
    nodes: dict[str, TopologyNode] = field(default_factory=dict)
    links: list[dict] = field(default_factory=list)
    state: str = "unknown"  # "deployed", "destroyed", "unknown"


class ContainerlabError(Exception):
    """Raised when a containerlab command fails."""


class TopologyManager:
    """Manages Containerlab topology lifecycle."""

    def __init__(self, topologies_dir: str | Path, runtime: str = "docker"):
        self.topologies_dir = Path(topologies_dir)
        self.runtime = runtime
        self._active_topology: TopologyInfo | None = None

    @property
    def active_topology(self) -> TopologyInfo | None:
        return self._active_topology

    def _run_clab(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run a containerlab command."""
        cmd = ["containerlab"] + args
        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        if check and result.returncode != 0:
            logger.error("containerlab failed: %s", result.stderr)
            raise ContainerlabError(
                f"containerlab {args[0]} failed (exit {result.returncode}): {result.stderr}"
            )
        return result

    def get_topology_file(self, name: str) -> Path:
        """Resolve a topology name to its YAML file path."""
        # Try exact filename first
        for pattern in [f"{name}.clab.yaml", f"{name}.clab.yml", f"{name}.yaml", f"{name}.yml"]:
            path = self.topologies_dir / pattern
            if path.exists():
                return path
        raise FileNotFoundError(
            f"Topology '{name}' not found in {self.topologies_dir}. "
            f"Available: {[f.name for f in self.topologies_dir.glob('*.clab.*')]}"
        )

    def deploy(self, topology_name: str, reconfigure: bool = False) -> TopologyInfo:
        """Deploy a Containerlab topology.

        Args:
            topology_name: Name of the topology (maps to a .clab.yaml file).
            reconfigure: If True, redeploy even if already running.

        Returns:
            TopologyInfo with node details.
        """
        topo_file = self.get_topology_file(topology_name)

        args = ["deploy", "--topo", str(topo_file)]
        if reconfigure:
            args.append("--reconfigure")

        self._run_clab(args)

        # Inspect to get node details
        info = self.inspect(topology_name)
        self._active_topology = info
        logger.info(
            "Topology '%s' deployed with %d nodes", topology_name, len(info.nodes)
        )
        return info

    def inspect(self, topology_name: str | None = None) -> TopologyInfo:
        """Inspect a running topology and return node details."""
        args = ["inspect", "--format", "json"]
        if topology_name:
            topo_file = self.get_topology_file(topology_name)
            args.extend(["--topo", str(topo_file)])

        result = self._run_clab(args, check=False)

        if result.returncode != 0:
            return TopologyInfo(
                name=topology_name or "unknown",
                topology_file="",
                state="not_found",
            )

        try:
            data = json.loads(result.stdout)
            nodes = {}

            # containerlab inspect JSON format: list of container entries
            containers = data if isinstance(data, list) else data.get("containers", [])

            for container in containers:
                name = container.get("name", "").split("clab-")[-1] if "clab-" in container.get("name", "") else container.get("name", "")
                # Extract the short name (after topology prefix)
                parts = name.split("-")
                short_name = parts[-1] if len(parts) > 1 else name

                node = TopologyNode(
                    name=short_name,
                    kind=container.get("kind", "linux"),
                    image=container.get("image", ""),
                    container_id=container.get("container_id", "")[:12],
                    ipv4_address=container.get("ipv4_address", "").split("/")[0],
                    ipv6_address=container.get("ipv6_address", "").split("/")[0],
                    state=container.get("state", "unknown"),
                )
                nodes[short_name] = node

            return TopologyInfo(
                name=topology_name or "unknown",
                topology_file=str(self.get_topology_file(topology_name)) if topology_name else "",
                nodes=nodes,
                state="deployed" if nodes else "empty",
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to parse inspect output: %s", e)
            return TopologyInfo(
                name=topology_name or "unknown",
                topology_file="",
                state="parse_error",
            )

    def destroy(self, topology_name: str, cleanup: bool = True) -> None:
        """Destroy a running topology."""
        topo_file = self.get_topology_file(topology_name)
        args = ["destroy", "--topo", str(topo_file)]
        if cleanup:
            args.append("--cleanup")

        self._run_clab(args, check=False)  # Don't fail if already destroyed
        self._active_topology = None
        logger.info("Topology '%s' destroyed", topology_name)

    def get_node_address(self, node_name: str) -> str:
        """Get the IPv4 address of a node in the active topology."""
        if not self._active_topology:
            raise RuntimeError("No active topology. Call deploy() first.")

        node = self._active_topology.nodes.get(node_name)
        if not node:
            available = list(self._active_topology.nodes.keys())
            raise KeyError(f"Node '{node_name}' not found. Available: {available}")
        return node.ipv4_address

    def exec_on_node(self, node_name: str, command: str, timeout: int = 30) -> str:
        """Execute a command inside a topology node container."""
        if not self._active_topology:
            raise RuntimeError("No active topology.")

        node = self._active_topology.nodes.get(node_name)
        if not node:
            raise KeyError(f"Node '{node_name}' not found")

        # Use docker exec with the container name
        container_name = f"clab-{self._active_topology.name}-{node_name}"
        cmd = [self.runtime, "exec", container_name] + command.split()

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise ContainerlabError(
                f"exec on {node_name} failed: {result.stderr}"
            )
        return result.stdout

    def list_topologies(self) -> list[str]:
        """List available topology definitions."""
        return sorted(
            f.stem.replace(".clab", "")
            for f in self.topologies_dir.glob("*.clab.*")
        )
