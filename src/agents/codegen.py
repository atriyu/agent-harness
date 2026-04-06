"""Test Code Generator Agent: generates pytest code from test plan specifications."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import TestPlan, TestSuite

SYSTEM_PROMPT = """\
You are an expert Python test automation engineer for networking products.

Generate executable pytest code for the given test suite specification. Follow these rules strictly:

CODE STRUCTURE RULES:
1. Every test function MUST start with `test_` and include a docstring with the test_id and traced requirement IDs
2. Use `@pytest.mark.parametrize` for protocol/variant coverage (e.g., parametrize over ["wireguard", "openvpn", "ikev2"])
3. Use `@pytest.mark.<category>` markers (vpn, l4, l7, performance, security, ha)
4. Use descriptive assertion messages: `assert result.is_up, f"Tunnel failed: {result.error}"`
5. Group related tests in classes when they share setup logic
6. Add `@pytest.mark.timeout(N)` for tests with specific timing requirements

AVAILABLE HELPER APIs:

```python
# VPN Testing (from src.networking.vpn import VPNHelper)
vpn = VPNHelper(topology_manager)
tunnel = vpn.establish_tunnel(protocol="wireguard", client_node="client", gateway_node="vpn-gw", timeout=30)
# tunnel.is_up, tunnel.status, tunnel.cipher, tunnel.handshake_time_ms, tunnel.error
vpn.verify_encryption(tunnel, expected_cipher="ChaCha20-Poly1305")  # -> bool
leak = vpn.check_dns_leak(client_node="client")  # -> LeakTestResult: .leak_detected, .leak_type, .details
leak = vpn.check_ip_leak(client_node="client", expected_vpn_ip="10.0.1.1")
leak = vpn.check_ipv6_leak(client_node="client")
vpn.test_kill_switch(client_node="client", protocol="wireguard")  # -> bool
vpn.teardown_tunnel(protocol="wireguard", client_node="client")

# Traffic Generation (from src.networking.traffic import TrafficGenerator)
tg = TrafficGenerator(topology_manager)
result = tg.iperf3(src="client", dst="server", protocol="tcp", duration=10, bandwidth="1G")
# result.bandwidth_mbps, result.jitter_ms, result.packet_loss_pct, result.success, result.error
sent = tg.scapy_send(src="client", packet_definition='IP(dst="10.0.2.1")/TCP(dport=80)', count=100)
resp = tg.http_request(src="client", url="http://10.0.1.1/api/health", method="GET", headers={"Host": "api.example.com"})
# resp.status_code, resp.headers, resp.body, resp.latency_ms
conn = tg.bulk_connections(src="client", dst="server", count=1000, port=80)
# conn.successful, conn.failed, conn.avg_latency_ms

# Protocol Validation (from src.networking.protocol import ProtocolValidator)
pv = ProtocolValidator(topology_manager)
tls = pv.testssl(target="10.0.1.1", port=443)
# tls.supported_protocols, tls.supported_ciphers, tls.pfs_supported, tls.has_vulnerabilities
pv.verify_tls_version(target="10.0.1.1", expected="TLSv1.3")  # -> bool
pv.verify_no_tls_version(target="10.0.1.1", rejected="TLSv1.0")  # -> bool
pv.verify_pfs(target="10.0.1.1")  # -> bool
scan = pv.nmap_scan(target="10.0.1.1", ports="1-1024")
# scan.open_ports, scan.services

# Packet Capture (from src.networking.capture import PacketCapture)
cap = PacketCapture(topology_manager, capture_dir="/tmp/captures")
cap_id = cap.start(node="client", interface="eth0", bpf_filter="port 80")
# ... generate traffic ...
result = cap.stop(cap_id)  # -> CaptureResult: .pcap_path, .packet_count
analysis = cap.analyze(result.pcap_path, display_filter="http")
# analysis.protocols, analysis.packet_count, analysis.packets
```

AVAILABLE FIXTURES (from conftest.py):
- `topology_manager` - TopologyManager with deployed topology
- `vpn_helper` - VPNHelper bound to the topology
- `traffic_gen` - TrafficGenerator bound to the topology
- `protocol_validator` - ProtocolValidator bound to the topology
- `packet_capture` - PacketCapture with output directory configured

ASSERTION PATTERNS:
- Tunnel up: `assert tunnel.is_up, f"Tunnel failed: {tunnel.error}"`
- No leak: `assert not leak.leak_detected, f"Leak: {leak.details}"`
- Bandwidth: `assert result.bandwidth_mbps >= 1000, f"Below threshold: {result.bandwidth_mbps}Mbps"`
- Latency: `assert resp.latency_ms < 50, f"Too slow: {resp.latency_ms}ms"`
- HTTP status: `assert resp.status_code == 200, f"Got {resp.status_code}: {resp.body[:100]}"`
- Port open: `assert 443 in scan.open_ports`

Output ONLY valid Python code, no markdown fences, no explanations.
"""

CONFTEST_TEMPLATE = '''\
"""Auto-generated conftest.py for the QA harness test suite."""

import os
import pytest
from pathlib import Path


def _get_topology_manager():
    """Create a TopologyManager, deploying if HARNESS_DEPLOY_TOPOLOGY is set."""
    from src.topology.manager import TopologyManager

    topo_dir = os.environ.get("HARNESS_TOPOLOGY_DIR", "config/topologies")
    manager = TopologyManager(topo_dir)

    topo_name = os.environ.get("HARNESS_TOPOLOGY", "")
    if topo_name:
        try:
            manager.deploy(topo_name)
        except Exception as e:
            pytest.skip(f"Topology deployment failed: {e}")

    return manager


@pytest.fixture(scope="session")
def topology_manager():
    """Provide a TopologyManager with optional auto-deployment."""
    manager = _get_topology_manager()
    yield manager
    # Teardown: destroy if we deployed
    if manager.active_topology and os.environ.get("HARNESS_DEPLOY_TOPOLOGY"):
        try:
            manager.destroy(manager.active_topology.name)
        except Exception:
            pass


@pytest.fixture
def vpn_helper(topology_manager):
    """Provide a VPN test helper bound to the topology."""
    from src.networking.vpn import VPNHelper
    return VPNHelper(topology_manager)


@pytest.fixture
def traffic_gen(topology_manager):
    """Provide a traffic generator bound to the topology."""
    from src.networking.traffic import TrafficGenerator
    return TrafficGenerator(topology_manager)


@pytest.fixture
def protocol_validator(topology_manager):
    """Provide a protocol validator bound to the topology."""
    from src.networking.protocol import ProtocolValidator
    return ProtocolValidator(topology_manager)


@pytest.fixture
def packet_capture(topology_manager, tmp_path):
    """Provide a packet capture helper with output directory."""
    from src.networking.capture import PacketCapture
    return PacketCapture(topology_manager, capture_dir=tmp_path / "captures")


# --- Pytest markers ---
def pytest_configure(config):
    """Register custom markers."""
    for marker in ["vpn", "l4", "l7", "performance", "security", "ha", "slow"]:
        config.addinivalue_line("markers", f"{marker}: mark test as {marker} category")
'''


class CodeGenAgent(BaseAgent):
    agent_name = "codegen"
    default_task_type = "test_code_generation"

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]
        output_dir = Path(inputs["config"]["harness"]["output_dir"]) / "test_code"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load test plan
        test_plan = store.load("test_plans", "test_plan.json", TestPlan)

        artifact_paths = []

        # Generate conftest.py
        conftest_path = output_dir / "conftest.py"
        conftest_path.write_text(CONFTEST_TEMPLATE)
        artifact_paths.append(str(conftest_path))

        # Generate a test file per suite
        for suite in test_plan.suites:
            code = await self._generate_suite(suite)
            if code:
                # Validate syntax
                code = self._validate_and_fix(code, suite)
                filename = f"test_{suite.category}_{suite.suite_id.lower().replace('-', '_')}.py"
                filepath = output_dir / filename
                filepath.write_text(code)
                artifact_paths.append(str(filepath))
                self.logger.info("Generated: %s (%d test cases)", filename, len(suite.test_cases))

        return {"artifact_paths": artifact_paths}

    async def _generate_suite(self, suite: TestSuite) -> str:
        """Generate pytest code for a single test suite."""
        # Build a summary of test cases for the LLM
        tc_specs = []
        for tc in suite.test_cases:
            steps_str = "\n".join(
                f"    Step {s.step_number}: {s.action} -> Expected: {s.expected}"
                for s in tc.steps
            )
            tc_specs.append(
                f"Test: {tc.test_id} - {tc.title}\n"
                f"  Traced reqs: {tc.traced_req_ids}\n"
                f"  Category: {tc.category}\n"
                f"  Priority: {tc.priority}\n"
                f"  Tools: {tc.tools}\n"
                f"  Topology: {tc.topology}\n"
                f"  Preconditions: {tc.preconditions}\n"
                f"  Steps:\n{steps_str}\n"
                f"  Expected result: {tc.expected_result}"
            )

        user_content = (
            f"Generate pytest code for suite: {suite.name} ({suite.suite_id})\n"
            f"Category: {suite.category}\n\n"
            f"Test cases:\n\n" + "\n\n".join(tc_specs)
        )

        return await self.llm_call(
            user_content=user_content,
            system=SYSTEM_PROMPT,
        )

    def _validate_and_fix(self, code: str, suite: TestSuite) -> str:
        """Validate generated Python code syntax. Return code or a stub on failure."""
        # Strip markdown fences if present
        if code.startswith("```"):
            code = code.split("\n", 1)[1].rsplit("```", 1)[0]

        try:
            ast.parse(code)
            return code
        except SyntaxError as e:
            self.logger.warning(
                "Syntax error in generated code for %s: %s. Generating stub.",
                suite.suite_id, e,
            )
            # Generate a minimal stub
            lines = [
                f'"""Auto-generated stub for {suite.name} (syntax error in LLM output)."""\n',
                "import pytest\n\n",
            ]
            for tc in suite.test_cases:
                func_name = tc.test_id.lower().replace("-", "_")
                lines.append(
                    f"@pytest.mark.skip(reason='Code generation failed - needs manual review')\n"
                    f"def test_{func_name}():\n"
                    f'    """{tc.test_id}: {tc.title}\n'
                    f"    Traces: {tc.traced_req_ids}\n"
                    f'    """\n'
                    f"    pass\n\n"
                )
            return "".join(lines)
