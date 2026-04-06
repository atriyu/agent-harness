"""Protocol validation helpers: TLS/SSL testing via testssl.sh, port scanning via nmap."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field

from src.topology.manager import TopologyManager

logger = logging.getLogger(__name__)


@dataclass
class TLSFinding:
    id: str
    severity: str  # "OK", "LOW", "MEDIUM", "HIGH", "CRITICAL", "INFO"
    finding: str


@dataclass
class TLSResult:
    target: str = ""
    port: int = 443
    supported_protocols: list[str] = field(default_factory=list)
    supported_ciphers: list[str] = field(default_factory=list)
    certificate_valid: bool = True
    certificate_subject: str = ""
    certificate_issuer: str = ""
    certificate_expiry: str = ""
    vulnerabilities: list[TLSFinding] = field(default_factory=list)
    pfs_supported: bool = False
    ocsp_stapling: bool = False
    error: str = ""

    @property
    def has_vulnerabilities(self) -> bool:
        return any(f.severity in ("HIGH", "CRITICAL") for f in self.vulnerabilities)


@dataclass
class PortInfo:
    port: int
    state: str  # "open", "closed", "filtered"
    service: str = ""
    version: str = ""
    protocol: str = "tcp"


@dataclass
class ScanResult:
    target: str = ""
    ports: list[PortInfo] = field(default_factory=list)
    os_guess: str = ""
    error: str = ""

    @property
    def open_ports(self) -> list[int]:
        return [p.port for p in self.ports if p.state == "open"]

    @property
    def services(self) -> dict[int, str]:
        return {p.port: p.service for p in self.ports if p.state == "open"}


class ProtocolValidator:
    """Protocol-level validation using testssl.sh and nmap.

    Can run commands either locally or on a topology node.
    """

    def __init__(self, topology_manager: TopologyManager | None = None, exec_node: str | None = None):
        self.topo = topology_manager
        self.exec_node = exec_node  # If set, run tools on this topology node

    def _run(self, cmd: str, timeout: int = 120) -> str:
        """Run a command locally or on a topology node."""
        if self.exec_node and self.topo and hasattr(self.topo, "exec_on_node"):
            return self.topo.exec_on_node(self.exec_node, cmd, timeout=timeout)

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout + result.stderr

    def testssl(
        self,
        target: str,
        port: int = 443,
        checks: list[str] | None = None,
        json_output: bool = True,
    ) -> TLSResult:
        """Run testssl.sh against a target.

        Args:
            target: Target hostname or IP.
            port: Target port.
            checks: Specific checks to run (e.g., ["-p", "-s", "-f"]).
            json_output: Use JSON output format for structured parsing.
        """
        cmd_parts = ["testssl.sh"]

        if json_output:
            cmd_parts.extend(["--jsonfile", "/tmp/testssl_result.json"])

        if checks:
            cmd_parts.extend(checks)
        else:
            # Default: run all standard checks
            cmd_parts.extend(["-p", "-s", "-f", "-U"])

        cmd_parts.append(f"{target}:{port}")
        cmd = " ".join(cmd_parts)

        try:
            self._run(cmd, timeout=180)

            if json_output:
                json_output_text = self._run("cat /tmp/testssl_result.json")
                return self._parse_testssl_json(json_output_text, target, port)
            else:
                output = self._run(cmd, timeout=180)
                return self._parse_testssl_text(output, target, port)

        except Exception as e:
            return TLSResult(target=target, port=port, error=str(e))

    def _parse_testssl_json(self, json_text: str, target: str, port: int) -> TLSResult:
        """Parse testssl.sh JSON output."""
        result = TLSResult(target=target, port=port)

        try:
            findings = json.loads(json_text)
            if not isinstance(findings, list):
                findings = findings.get("scanResult", [{}])[0].get("findings", [])

            for finding in findings:
                fid = finding.get("id", "")
                severity = finding.get("severity", "INFO")
                ftext = finding.get("finding", "")

                # Extract protocol support
                if fid.startswith("protocol_"):
                    proto = fid.replace("protocol_", "").replace("_", ".")
                    if "offered" in ftext.lower() or "yes" in ftext.lower():
                        result.supported_protocols.append(proto)

                # Extract cipher info
                elif "cipher" in fid.lower():
                    if severity in ("OK", "INFO"):
                        result.supported_ciphers.append(ftext.split()[0] if ftext else fid)

                # Certificate info
                elif "cert" in fid.lower():
                    if "subject" in fid:
                        result.certificate_subject = ftext
                    elif "issuer" in fid:
                        result.certificate_issuer = ftext
                    elif "expir" in fid:
                        result.certificate_expiry = ftext

                # PFS
                elif "pfs" in fid.lower() or "forward_secrecy" in fid.lower():
                    result.pfs_supported = severity in ("OK", "INFO")

                # OCSP
                elif "ocsp" in fid.lower() and "stapling" in fid.lower():
                    result.ocsp_stapling = "yes" in ftext.lower() or severity == "OK"

                # Vulnerabilities
                if severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                    result.vulnerabilities.append(TLSFinding(
                        id=fid, severity=severity, finding=ftext,
                    ))

        except (json.JSONDecodeError, KeyError) as e:
            result.error = f"Failed to parse testssl JSON: {e}"

        return result

    def _parse_testssl_text(self, output: str, target: str, port: int) -> TLSResult:
        """Fallback: parse testssl.sh text output."""
        result = TLSResult(target=target, port=port)

        for line in output.split("\n"):
            line = line.strip()
            if "TLSv1.2" in line and ("offered" in line or "YES" in line):
                result.supported_protocols.append("TLSv1.2")
            if "TLSv1.3" in line and ("offered" in line or "YES" in line):
                result.supported_protocols.append("TLSv1.3")
            if "Forward Secrecy" in line and ("OK" in line or "offered" in line):
                result.pfs_supported = True
            if "OCSP stapling" in line and ("yes" in line.lower() or "offered" in line.lower()):
                result.ocsp_stapling = True
            if "VULNERABLE" in line:
                result.vulnerabilities.append(TLSFinding(
                    id="text_parse", severity="HIGH", finding=line,
                ))

        return result

    def nmap_scan(
        self,
        target: str,
        ports: str = "1-1024",
        flags: str = "-sV",
        protocol: str = "tcp",
    ) -> ScanResult:
        """Run an nmap scan against a target.

        Args:
            target: Target hostname or IP.
            ports: Port specification (e.g., "22,80,443" or "1-1024").
            flags: Nmap flags (e.g., "-sV" for version detection).
            protocol: "tcp" or "udp".
        """
        cmd_parts = ["nmap"]

        if protocol == "udp":
            cmd_parts.append("-sU")

        cmd_parts.extend([flags, "-p", ports, "-oX", "-", target])
        cmd = " ".join(cmd_parts)

        try:
            output = self._run(cmd, timeout=120)
            return self._parse_nmap_xml(output, target)
        except Exception as e:
            return ScanResult(target=target, error=str(e))

    def _parse_nmap_xml(self, xml_output: str, target: str) -> ScanResult:
        """Parse nmap XML output."""
        result = ScanResult(target=target)

        # Simple regex parsing (avoid xml.etree for robustness with partial output)
        for match in re.finditer(
            r'<port protocol="(\w+)" portid="(\d+)">'
            r'<state state="(\w+)"[^/]*/>'
            r'(?:<service name="([^"]*)"(?:\s+product="([^"]*)")?(?:\s+version="([^"]*)")?)?',
            xml_output,
        ):
            proto, port_str, state, service, product, version = match.groups()
            result.ports.append(PortInfo(
                port=int(port_str),
                state=state,
                service=service or "",
                version=f"{product or ''} {version or ''}".strip(),
                protocol=proto,
            ))

        # OS detection
        os_match = re.search(r'<osmatch name="([^"]+)"', xml_output)
        if os_match:
            result.os_guess = os_match.group(1)

        return result

    def verify_tls_version(
        self, target: str, expected: str = "TLSv1.3", port: int = 443,
    ) -> bool:
        """Verify a specific TLS version is supported."""
        result = self.testssl(target, port=port, checks=["-p"])
        return expected in result.supported_protocols

    def verify_no_tls_version(
        self, target: str, rejected: str = "TLSv1.0", port: int = 443,
    ) -> bool:
        """Verify a TLS version is NOT supported (rejected)."""
        result = self.testssl(target, port=port, checks=["-p"])
        return rejected not in result.supported_protocols

    def verify_cipher_suite(
        self, target: str, expected_ciphers: list[str], port: int = 443,
    ) -> bool:
        """Verify specific cipher suites are supported."""
        result = self.testssl(target, port=port, checks=["-s"])
        return all(c in result.supported_ciphers for c in expected_ciphers)

    def verify_pfs(self, target: str, port: int = 443) -> bool:
        """Verify Perfect Forward Secrecy is supported."""
        result = self.testssl(target, port=port, checks=["-f"])
        return result.pfs_supported

    def verify_no_vulnerabilities(self, target: str, port: int = 443) -> bool:
        """Verify no HIGH/CRITICAL vulnerabilities found."""
        result = self.testssl(target, port=port, checks=["-U"])
        return not result.has_vulnerabilities
