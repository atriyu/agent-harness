"""Gap Analysis Agent: compares test plan capabilities against available APIs.

Identifies missing methods, parameters, and return fields that the test plan
requires but the networking helper APIs don't yet provide. Produces a structured
GapReport that the API Enhancement Agent can act on.
"""

from __future__ import annotations

import json
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import (
    APIGap,
    GapReport,
    GapType,
    TestPlan,
)


class GapAnalysisAgent(BaseAgent):
    agent_name = "gap_analysis"
    default_task_type = "gap_analysis"
    core_system_prompt = """\
You are a test infrastructure analyst. Compare what a test plan requires against
what the available test helper APIs provide, and identify ALL gaps.

GAP TYPES (check all five):

1. missing_method: A method that should exist in an existing module but doesn't.
   Example: vpn.py has VPNHelper but no check_mtu() method.

2. missing_parameter: A method exists but lacks a needed parameter.
   Example: establish_tunnel() needs mode="tcp" but only has protocol.

3. missing_return_field: A method's return type lacks a field the test needs.
   Example: IperfResult has bandwidth_mbps but not packets_per_second.

4. missing_tool: The test plan requires a CLI tool that NO existing module wraps.
   Example: Tests need wget for recursive HTTP download testing, but no module wraps wget.
   Common tools that might be missing: wget, ab (Apache Bench), wrk, hey (HTTP load),
   mtr (traceroute), dig (DNS), openssl s_client, socat, netcat, tc (traffic control).

5. missing_module: An entirely new helper module is needed for a category of tests
   that no existing module covers.
   Example: Tests need HTTP client testing (cookies, redirects, auth) but only traffic.py
   exists which has basic curl support. A dedicated http_client.py module is needed.

SEVERITY:
- critical: Test CANNOT run without this. Blocks requirements.
- minor: Test can partially work around it.

For missing_tool and missing_module gaps, include:
- tool_name: The CLI tool needed (e.g., "wget", "wrk", "mtr")
- suggested_module: Where to put it (e.g., "src/networking/http_client.py")

Output a JSON object:
{
  "gaps": [
    {
      "gap_id": "GAP-001",
      "severity": "critical",
      "test_ids": ["TC-L7-HTTP-005"],
      "req_ids": ["REQ-L7-003"],
      "module": "",
      "gap_type": "missing_tool",
      "description": "Need wget wrapper for recursive HTTP download and cookie persistence testing",
      "suggested_signature": "",
      "tool_name": "wget",
      "suggested_module": "src/networking/http_client.py"
    },
    {
      "gap_id": "GAP-002",
      "severity": "critical",
      "test_ids": ["TC-VPN-TCP-001"],
      "req_ids": ["REQ-VPN-005"],
      "module": "src/networking/vpn.py",
      "gap_type": "missing_parameter",
      "description": "establish_tunnel() needs mode parameter for TCP transport",
      "suggested_signature": "def establish_tunnel(self, protocol='wireguard', mode='udp', ...)",
      "tool_name": "",
      "suggested_module": ""
    }
  ]
}

If there are no gaps, output: {"gaps": []}

Output ONLY the JSON object.
"""

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]
        config = inputs["config"]

        gap_config = config.get("gap_analysis", {})
        if not gap_config.get("enabled", True):
            self.logger.info("Gap analysis is disabled")
            empty_report = GapReport(plan_id="", gaps=[], all_resolvable=True)
            return {"artifact_paths": [], "gap_report": empty_report}

        # Load test plan
        test_plan = store.load("test_plans", "test_plan.json", TestPlan)

        # Gather API surface from skills or direct source inspection
        api_surface = self._gather_api_surface(config)

        # Extract test plan capability requirements
        capability_summary = self._summarize_plan_capabilities(test_plan)

        # List existing modules so the agent knows what's covered
        existing_modules = self._list_existing_modules()

        user_content = (
            f"## Test Plan Capabilities Required\n\n{capability_summary}\n\n"
            f"## Available API Surface\n\n{api_surface}\n\n"
            f"## Existing Helper Modules\n{existing_modules}\n\n"
            f"Identify ALL gaps: missing methods, missing parameters, missing return fields, "
            f"missing CLI tool integrations, and missing helper modules. "
            f"Check whether any test steps require tools not wrapped by any existing module."
        )

        raw = await self.llm_call(user_content=user_content)

        # Parse response
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        gap_data = json.loads(text)

        gaps = []
        for g in gap_data.get("gaps", []):
            gaps.append(APIGap(
                gap_id=g.get("gap_id", f"GAP-{len(gaps)+1:03d}"),
                severity=g.get("severity", "minor"),
                test_ids=g.get("test_ids", []),
                req_ids=g.get("req_ids", []),
                module=g.get("module", ""),
                gap_type=g.get("gap_type", "missing_method"),
                description=g.get("description", ""),
                suggested_signature=g.get("suggested_signature", ""),
                tool_name=g.get("tool_name", ""),
                suggested_module=g.get("suggested_module", ""),
            ))

        critical = sum(1 for g in gaps if g.severity == "critical")
        minor = sum(1 for g in gaps if g.severity == "minor")

        report = GapReport(
            plan_id=test_plan.plan_id,
            gaps=gaps,
            total_critical=critical,
            total_minor=minor,
            all_resolvable=True,  # Assume resolvable; enhance agent will update
        )

        path = store.save("gap_analysis", "gap_report.json", report)
        self.logger.info(
            "Gap analysis: %d gaps (%d critical, %d minor)",
            len(gaps), critical, minor,
        )

        # Check gap policy
        if critical > 0:
            policy = gap_config.get("policy", "configurable")
            action = gap_config.get("critical_action", "pause") if policy == "configurable" else policy
            if action == "pause":
                self.logger.warning(
                    "Critical API gaps found. Pipeline will attempt auto-enhancement."
                )

        return {"artifact_paths": [str(path)], "gap_report": report}

    def _gather_api_surface(self, config: dict) -> str:
        """Gather the current API surface from auto-generated API skills or source."""
        from pathlib import Path

        # Try to read from api-reference skills
        skills_dir = Path(config.get("skills", {}).get("skills_dir", "skills"))
        api_dir = skills_dir / "api-reference"

        if api_dir.exists():
            parts = []
            for md in sorted(api_dir.glob("*.md")):
                content = md.read_text()
                # Strip frontmatter
                if content.startswith("---"):
                    content = content.split("---", 2)[2].strip()
                parts.append(f"### {md.stem}\n\n{content}")
            if parts:
                return "\n\n".join(parts)

        # Fallback: read source files directly
        net_dir = Path("src/networking")
        if net_dir.exists():
            parts = []
            for py in sorted(net_dir.glob("*.py")):
                if py.name.startswith("_"):
                    continue
                parts.append(f"### {py.stem}\n```python\n{py.read_text()[:3000]}\n```")
            return "\n\n".join(parts)

        return "No API documentation available."

    def _summarize_plan_capabilities(self, test_plan: TestPlan) -> str:
        """Extract what capabilities the test plan needs from its test cases."""
        lines = []
        for suite in test_plan.suites:
            for tc in suite.test_cases:
                tools_str = ", ".join(tc.tools) if tc.tools else "general"
                steps_str = "; ".join(f"{s.action}" for s in tc.steps)
                lines.append(
                    f"- **{tc.test_id}** ({tc.category}, topology={tc.topology}): "
                    f"tools=[{tools_str}] | Steps: {steps_str}"
                )
        return "\n".join(lines) if lines else "No test cases in plan."

    def _list_existing_modules(self) -> str:
        """List existing networking helper modules and the tools they wrap."""
        from pathlib import Path

        net_dir = Path("src/networking")
        if not net_dir.exists():
            return "No networking modules found."

        lines = ["Existing helper modules and the CLI tools they wrap:"]
        # Map of module -> known tools (from module docstrings/imports)
        tool_hints = {
            "vpn": "WireGuard (wg, wg-quick), OpenVPN (openvpn), IKEv2 (ipsec/strongSwan), tcpdump, curl",
            "traffic": "iperf3, scapy, curl",
            "protocol": "testssl.sh, nmap",
            "capture": "tcpdump, tshark",
        }

        for py in sorted(net_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            stem = py.name.replace(".py", "")
            tools = tool_hints.get(stem, "unknown")
            lines.append(f"- src/networking/{py.name}: wraps [{tools}]")

        lines.append("")
        lines.append(
            "Tools NOT currently wrapped by any module include: "
            "wget, ab/wrk/hey (HTTP load testing), mtr (traceroute), "
            "dig (DNS queries), openssl s_client, socat, netcat/nc, "
            "tc (traffic control/netem), ethtool, ss, conntrack."
        )
        return "\n".join(lines)
