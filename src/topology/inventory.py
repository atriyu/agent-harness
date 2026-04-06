"""Dynamic inventory from a running Containerlab topology.

Provides a structured view of the topology for test fixtures and
networking helpers to consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.topology.manager import TopologyInfo, TopologyManager


@dataclass
class NodeInventoryEntry:
    name: str
    role: str  # "client", "server", "vpn_gateway", "lb", "proxy"
    ipv4: str
    ipv6: str = ""
    ssh_port: int = 22
    interfaces: dict[str, str] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class TopologyInventory:
    """Structured inventory of all nodes in a topology, organized by role."""
    topology_name: str
    nodes: dict[str, NodeInventoryEntry] = field(default_factory=dict)

    def by_role(self, role: str) -> list[NodeInventoryEntry]:
        return [n for n in self.nodes.values() if n.role == role]

    def get(self, name: str) -> NodeInventoryEntry:
        if name not in self.nodes:
            raise KeyError(f"Node '{name}' not in inventory. Available: {list(self.nodes.keys())}")
        return self.nodes[name]

    @property
    def clients(self) -> list[NodeInventoryEntry]:
        return self.by_role("client")

    @property
    def servers(self) -> list[NodeInventoryEntry]:
        return self.by_role("server")

    @property
    def gateways(self) -> list[NodeInventoryEntry]:
        return self.by_role("vpn_gateway")


# Role inference from node naming conventions
ROLE_PATTERNS = {
    "client": ["client", "cli", "host"],
    "server": ["server", "srv", "backend"],
    "vpn_gateway": ["vpn", "gateway", "gw"],
    "lb": ["lb", "loadbalancer", "balancer"],
    "proxy": ["proxy", "l7", "waf", "reverse"],
    "firewall": ["fw", "firewall"],
}


def _infer_role(node_name: str) -> str:
    """Infer a node's role from its name."""
    lower = node_name.lower()
    for role, patterns in ROLE_PATTERNS.items():
        if any(pat in lower for pat in patterns):
            return role
    return "unknown"


def build_inventory(topo_info: TopologyInfo) -> TopologyInventory:
    """Build a structured inventory from a TopologyInfo."""
    inventory = TopologyInventory(topology_name=topo_info.name)

    for name, node in topo_info.nodes.items():
        entry = NodeInventoryEntry(
            name=name,
            role=_infer_role(name),
            ipv4=node.ipv4_address,
            ipv6=node.ipv6_address,
            interfaces=node.interfaces,
        )
        inventory.nodes[name] = entry

    return inventory


def build_inventory_from_manager(manager: TopologyManager) -> TopologyInventory:
    """Build inventory from the currently active topology in a manager."""
    if not manager.active_topology:
        raise RuntimeError("No active topology in manager")
    return build_inventory(manager.active_topology)
