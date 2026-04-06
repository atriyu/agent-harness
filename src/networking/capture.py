"""Packet capture helpers: tcpdump/tshark wrappers for topology nodes."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.topology.manager import TopologyManager

logger = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    pcap_path: str = ""
    packet_count: int = 0
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error and self.packet_count > 0


@dataclass
class PacketSummary:
    src_ip: str = ""
    dst_ip: str = ""
    protocol: str = ""
    length: int = 0
    info: str = ""


@dataclass
class AnalysisResult:
    packet_count: int = 0
    protocols: dict[str, int] = field(default_factory=dict)  # protocol -> count
    conversations: list[dict] = field(default_factory=list)
    packets: list[PacketSummary] = field(default_factory=list)
    summary: str = ""
    error: str = ""


class PacketCapture:
    """Packet capture and analysis via tcpdump/tshark on topology nodes."""

    def __init__(
        self,
        topology_manager: TopologyManager | Any = None,
        capture_dir: str | Path = "/tmp/captures",
        exec_node: str | None = None,
    ):
        self.topo = topology_manager
        self.capture_dir = Path(capture_dir)
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.exec_node = exec_node
        self._active_capture: dict[str, dict] = {}

    def _exec(self, node: str, cmd: str, timeout: int = 60) -> str:
        if node and self.topo and hasattr(self.topo, "exec_on_node"):
            return self.topo.exec_on_node(node, cmd, timeout=timeout)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout

    def start(
        self,
        node: str | None = None,
        interface: str = "any",
        bpf_filter: str = "",
        max_packets: int = 0,
        capture_name: str = "capture",
    ) -> str:
        """Start a packet capture on a node.

        Args:
            node: Topology node to capture on. None = local.
            interface: Network interface (default "any").
            bpf_filter: BPF filter expression (e.g., "port 80", "tcp", "host 10.0.0.1").
            max_packets: Stop after this many packets. 0 = unlimited.
            capture_name: Name for the capture file.

        Returns:
            Capture ID for use with stop() and analyze().
        """
        target_node = node or self.exec_node or ""
        pcap_path = f"/tmp/{capture_name}_{int(time.time())}.pcap"

        cmd_parts = [
            "tcpdump", "-i", interface,
            "-w", pcap_path,
            "-U",  # Unbuffered output
        ]
        if max_packets:
            cmd_parts.extend(["-c", str(max_packets)])
        if bpf_filter:
            cmd_parts.append(bpf_filter)

        # Run in background
        cmd = " ".join(cmd_parts) + " &"
        self._exec(target_node, cmd)

        capture_id = f"{target_node}:{capture_name}"
        self._active_capture[capture_id] = {
            "node": target_node,
            "pcap_path": pcap_path,
            "start_time": time.time(),
        }

        logger.info("Capture started: %s on %s (filter: %s)", capture_id, interface, bpf_filter or "none")
        return capture_id

    def stop(self, capture_id: str) -> CaptureResult:
        """Stop an active capture and return results."""
        if capture_id not in self._active_capture:
            return CaptureResult(error=f"Unknown capture: {capture_id}")

        info = self._active_capture.pop(capture_id)
        node = info["node"]

        # Kill tcpdump
        self._exec(node, "pkill -f tcpdump || true")
        time.sleep(0.5)

        # Get capture stats
        try:
            stat_output = self._exec(node, f"tcpdump -r {info['pcap_path']} 2>&1 | wc -l")
            packet_count = int(stat_output.strip()) if stat_output.strip().isdigit() else 0

            ls_output = self._exec(node, f"stat -c %s {info['pcap_path']} 2>/dev/null || stat -f %z {info['pcap_path']} 2>/dev/null || echo 0")
            file_size = int(ls_output.strip()) if ls_output.strip().isdigit() else 0

            # Copy pcap to local capture directory if running on a remote node
            local_path = str(self.capture_dir / Path(info["pcap_path"]).name)
            if node and self.topo:
                # For containerlab, we can docker cp
                try:
                    subprocess.run(
                        ["docker", "cp", f"clab-{node}:{info['pcap_path']}", local_path],
                        capture_output=True, timeout=30,
                    )
                except Exception:
                    local_path = info["pcap_path"]
            else:
                local_path = info["pcap_path"]

            return CaptureResult(
                pcap_path=local_path,
                packet_count=packet_count,
                duration_seconds=time.time() - info["start_time"],
                file_size_bytes=file_size,
            )

        except Exception as e:
            return CaptureResult(error=str(e))

    def analyze(
        self,
        pcap_path: str,
        display_filter: str = "",
        max_packets: int = 100,
        node: str | None = None,
    ) -> AnalysisResult:
        """Analyze a pcap file using tshark.

        Args:
            pcap_path: Path to the pcap file.
            display_filter: Wireshark display filter (e.g., "http", "tls", "dns").
            max_packets: Maximum packets to analyze.
            node: Node to run tshark on (None = local).
        """
        target = node or self.exec_node or ""

        # Get protocol statistics
        cmd = f"tshark -r {pcap_path} -q -z io,phs"
        if display_filter:
            cmd += f" -Y '{display_filter}'"

        try:
            stats_output = self._exec(target, cmd, timeout=60)
        except Exception:
            stats_output = ""

        # Get packet list
        fields_cmd = (
            f"tshark -r {pcap_path} -T fields "
            f"-e ip.src -e ip.dst -e _ws.col.Protocol -e frame.len -e _ws.col.Info "
            f"-c {max_packets}"
        )
        if display_filter:
            fields_cmd += f" -Y '{display_filter}'"

        try:
            packets_output = self._exec(target, fields_cmd, timeout=60)
        except Exception:
            packets_output = ""

        # Parse results
        result = AnalysisResult()

        # Parse protocol hierarchy
        protocols: dict[str, int] = {}
        for line in stats_output.split("\n"):
            match = re.search(r"(\w+)\s+frames:(\d+)", line)
            if match:
                protocols[match.group(1)] = int(match.group(2))
        result.protocols = protocols

        # Parse packet list
        packets = []
        for line in packets_output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                packets.append(PacketSummary(
                    src_ip=parts[0],
                    dst_ip=parts[1],
                    protocol=parts[2],
                    length=int(parts[3]) if parts[3].isdigit() else 0,
                    info=parts[4] if len(parts) > 4 else "",
                ))

        result.packets = packets
        result.packet_count = len(packets)

        # Build summary
        if protocols:
            top_protos = sorted(protocols.items(), key=lambda x: x[1], reverse=True)[:5]
            result.summary = "Top protocols: " + ", ".join(
                f"{p}({c})" for p, c in top_protos
            )

        return result

    def capture_and_analyze(
        self,
        node: str | None = None,
        interface: str = "any",
        bpf_filter: str = "",
        duration_seconds: int = 5,
        display_filter: str = "",
    ) -> AnalysisResult:
        """Convenience: capture for a duration, then analyze."""
        capture_id = self.start(
            node=node, interface=interface, bpf_filter=bpf_filter,
            capture_name=f"quick_{int(time.time())}",
        )

        time.sleep(duration_seconds)
        result = self.stop(capture_id)

        if not result.success:
            return AnalysisResult(error=result.error)

        return self.analyze(result.pcap_path, display_filter=display_filter, node=node)
