"""Tests for topology manager, inventory, and health checks."""

from pathlib import Path

from src.topology.manager import TopologyManager, TopologyInfo, TopologyNode
from src.topology.inventory import build_inventory, _infer_role, TopologyInventory


def test_topology_manager_list(tmp_path):
    """Test listing available topologies."""
    topo_dir = tmp_path / "topologies"
    topo_dir.mkdir()
    (topo_dir / "vpn_basic.clab.yaml").write_text("name: vpn-basic\n")
    (topo_dir / "l4_lb.clab.yaml").write_text("name: l4-lb\n")

    manager = TopologyManager(topo_dir)
    topos = manager.list_topologies()
    assert "vpn_basic" in topos
    assert "l4_lb" in topos


def test_topology_manager_get_file(tmp_path):
    """Test resolving topology name to file path."""
    topo_dir = tmp_path / "topologies"
    topo_dir.mkdir()
    (topo_dir / "test.clab.yaml").write_text("name: test\n")

    manager = TopologyManager(topo_dir)
    path = manager.get_topology_file("test")
    assert path.exists()
    assert path.name == "test.clab.yaml"


def test_topology_manager_file_not_found(tmp_path):
    """Test error when topology not found."""
    manager = TopologyManager(tmp_path)
    import pytest
    with pytest.raises(FileNotFoundError, match="not found"):
        manager.get_topology_file("nonexistent")


def test_infer_role():
    """Test role inference from node names."""
    assert _infer_role("vpn-gw") == "vpn_gateway"
    assert _infer_role("client1") == "client"
    assert _infer_role("backend-server") == "server"
    assert _infer_role("lb-01") == "lb"
    assert _infer_role("l7-proxy") == "proxy"
    assert _infer_role("firewall-edge") == "firewall"
    assert _infer_role("randomnode") == "unknown"


def test_build_inventory():
    """Test building inventory from topology info."""
    topo_info = TopologyInfo(
        name="test-topo",
        topology_file="/tmp/test.clab.yaml",
        nodes={
            "client": TopologyNode(name="client", kind="linux", image="test:latest", ipv4_address="10.0.0.2"),
            "vpn-gw": TopologyNode(name="vpn-gw", kind="linux", image="vpn:latest", ipv4_address="10.0.0.1"),
            "server": TopologyNode(name="server", kind="linux", image="test:latest", ipv4_address="10.0.1.1"),
        },
        state="deployed",
    )

    inventory = build_inventory(topo_info)
    assert inventory.topology_name == "test-topo"
    assert len(inventory.nodes) == 3
    assert inventory.get("client").role == "client"
    assert inventory.get("vpn-gw").role == "vpn_gateway"
    assert inventory.get("server").role == "server"
    assert len(inventory.clients) == 1
    assert len(inventory.gateways) == 1
    assert len(inventory.servers) == 1


def test_inventory_by_role():
    """Test filtering inventory by role."""
    inventory = TopologyInventory(topology_name="test")
    from src.topology.inventory import NodeInventoryEntry
    inventory.nodes["c1"] = NodeInventoryEntry(name="c1", role="client", ipv4="10.0.0.1")
    inventory.nodes["c2"] = NodeInventoryEntry(name="c2", role="client", ipv4="10.0.0.2")
    inventory.nodes["s1"] = NodeInventoryEntry(name="s1", role="server", ipv4="10.0.1.1")

    assert len(inventory.by_role("client")) == 2
    assert len(inventory.by_role("server")) == 1
    assert len(inventory.by_role("proxy")) == 0
