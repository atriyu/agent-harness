---
name: enhancement-patterns
description: Patterns and conventions for how networking test helper APIs are structured, for use when generating new wrapper methods
domain: api-enhancement
applies_to: [api_enhance]
priority: 1
tags: [api, patterns, codegen, infrastructure]
---

## Helper Module Conventions

All networking helper modules follow these patterns:

### Constructor Pattern
```python
class SomeHelper:
    def __init__(self, topology_manager: TopologyManager | Any):
        self.topo = topology_manager
    
    def _exec(self, node: str, cmd: str, timeout: int = 60) -> str:
        if hasattr(self.topo, "exec_on_node"):
            return self.topo.exec_on_node(node, cmd, timeout=timeout)
        return ""
```

### Method Pattern
```python
def some_operation(self, node: str = "client", param: str = "default", timeout: int = 30) -> SomeResult:
    """One-line description.
    
    Args:
        node: Topology node to execute on.
        param: What this controls.
        timeout: Seconds to wait.
    """
    cmd = f"tool --flag {param}"
    try:
        output = self._exec(node, cmd, timeout=timeout)
        return self._parse_output(output)
    except Exception as e:
        return SomeResult(error=str(e))
```

### Return Type Pattern
All return types are dataclasses with:
- Typed fields for structured data
- An `error: str = ""` field for error reporting
- A `success` or `is_up` property that checks `not self.error`

```python
@dataclass
class SomeResult:
    value: float = 0.0
    details: str = ""
    error: str = ""
    
    @property
    def success(self) -> bool:
        return not self.error
```

### CLI Tool Wrappers
- **iperf3**: `iperf3 -c <target> -t <duration> --json` → parse JSON output
- **testssl.sh**: `testssl.sh --jsonfile /tmp/result.json <target>` → parse JSON
- **nmap**: `nmap -oX - <target>` → parse XML output
- **tcpdump**: `tcpdump -i <iface> -w <pcap> <filter>` → capture file
- **tshark**: `tshark -r <pcap> -T fields -e <fields>` → parsed text
- **wg**: `wg show <iface>` → parse text output
- **wstunnel**: `wstunnel --udp-to-tcp <target>` → WireGuard-over-TCP
- **openvpn**: `openvpn --config <conf> --daemon` → verify tun interface
- **ipsec**: `ipsec up <conn>` / `ipsec status` → parse status text
- **curl**: `curl -s -w "%{http_code}|%{time_total}" -o /tmp/body <url>` → parse status + timing

### Adding Parameters to Existing Methods
1. Always add with a default value (backward compatible)
2. Branch behavior on the new parameter
3. Keep existing behavior unchanged at default value
4. Update docstring with new parameter

### Adding New Methods
1. Place in the correct class (VPNHelper, TrafficGenerator, etc.)
2. Follow the _exec pattern
3. Return a typed dataclass
4. Handle subprocess failures gracefully
5. Log at debug/info level
