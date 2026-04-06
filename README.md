# Agent Harness — Autonomous QA for VPN & L4-L7 Networking Products

An agentic pipeline that transforms product requirement documents into comprehensive QA reports — fully autonomously. Drop in a PRD, get back a test plan, generated tests, execution results, failure triage, and a stakeholder-ready report. No human intervention required between stages.

```
PRD / Spec ──► Ingest ──► Extract ──► Plan ──► CodeGen ──► Execute ──► Triage ──► Report
               (Haiku)   (Sonnet)    (Opus)   (Sonnet)   (no LLM)    (Opus)    (Haiku)
```

---

## Table of Contents

- [How Autonomous QA Works](#how-autonomous-qa-works)
- [Architecture](#architecture)
  - [Pipeline Stages](#pipeline-stages)
  - [Model Routing & Cost Optimization](#model-routing--cost-optimization)
  - [Typed Artifact Contracts](#typed-artifact-contracts)
  - [Self-Healing Repair Loop](#self-healing-repair-loop)
  - [Checkpoint & Resume](#checkpoint--resume)
- [Networking Test Infrastructure](#networking-test-infrastructure)
  - [Containerlab Topologies](#containerlab-topologies)
  - [Networking Helpers](#networking-helpers)
- [User Workflow](#user-workflow)
  - [Quick Start](#quick-start)
  - [CLI Reference](#cli-reference)
  - [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Extending the Harness](#extending-the-harness)

---

## How Autonomous QA Works

Traditional QA pipelines require human involvement at every stage — an analyst reads the spec, a test architect writes the plan, an automation engineer codes the tests, a QA lead triages failures, and a manager reads the report. This harness replaces that chain with a pipeline of specialized LLM agents, each operating on typed artifacts produced by the previous stage.

**The autonomy comes from six design decisions:**

### 1. Structured Artifacts as Agent Contracts

Every agent produces and consumes typed Pydantic models — not freeform text. The requirement extraction agent outputs a `RequirementSet` with tagged, prioritized requirements. The plan agent receives that exact schema and produces a `TestPlan` with `TestSuite[]` and `TestCaseSpec[]`. The code generation agent receives test specs and produces valid Python. Each schema enforces completeness: a test case without `traced_req_ids` won't validate, so traceability is structural, not aspirational.

This means each agent can operate independently — it trusts its inputs because the schema guarantees structure, and its outputs are validated before the next agent sees them.

### 2. Externalized Domain Skills

Domain expertise is not hardcoded in agent Python code. Instead, it lives in **skill files** — markdown documents with YAML frontmatter stored in the `skills/` directory. Each agent keeps a slim core prompt (role + output format) in Python, and domain knowledge is injected at runtime by the **Skills Framework**.

```
skills/
├── domains/           # Protocol & service expertise
│   ├── vpn-protocols.md        ← WireGuard, OpenVPN, IKEv2 test patterns
│   ├── l4-load-balancing.md    ← LB algorithms, NAT, connection tracking
│   └── l7-application.md       ← TLS, WAF, routing, session affinity
├── test-patterns/     # Cross-cutting test strategies
│   ├── security-testing.md     ← OWASP, cipher validation, PFS
│   ├── performance-testing.md  ← iperf3 baselines, latency percentiles
│   └── negative-testing.md     ← Error injection, boundary conditions
├── triage/            # Diagnostic frameworks
│   ├── diagnostic-framework.md ← 5-step root cause analysis
│   └── failure-patterns.md     ← Error classification heuristics
├── api-reference/     # Auto-generated from Python code
│   ├── vpn-api.md              ← Generated from src/networking/vpn.py
│   └── traffic-api.md          ← Generated from src/networking/traffic.py
└── products/          # Product-specific overrides
    └── secureconnect/
        └── product-context.md  ← Product-specific test priorities
```

A skill file looks like this:

```markdown
---
name: vpn-protocols
description: VPN protocol test expertise for WireGuard, OpenVPN, and IKEv2
domain: vpn
applies_to: [plan, codegen, triage]
priority: 1
---

## WireGuard Testing Patterns
- Handshake must complete within 5 seconds
- Verify ChaCha20-Poly1305 cipher in packet capture
...
```

The `applies_to` field controls which agents receive the skill. The `priority` field determines loading order when the token budget is tight. Skills are discovered at startup, loaded progressively (metadata first, content on demand), and composed into agent prompts by the `SkillInjector`.

This means a **network QA engineer can add test expertise by writing a markdown file** — no Python, no code review of agent logic, no redeployment. The skills framework handles discovery, matching, and injection automatically.

**API reference skills are auto-generated** from Python docstrings at each pipeline run, so the codegen agent always sees the true, current API of every networking helper module — no manual synchronization needed.

### 3. Intelligent Model Routing

Not every task needs the most powerful model. Document parsing is simple extraction — Haiku handles it for $0.001/1K tokens. Test plan design requires complex multi-step reasoning about edge cases and cross-feature interactions — Opus handles it at $0.015/1K tokens. This explicit routing reduces cost by 30-70% compared to using Opus for everything, while concentrating reasoning power where it matters most.

If a cheaper model produces output that fails schema validation, the router automatically escalates to the next tier (Haiku → Sonnet → Opus). This cascade ensures reliability without defaulting to expensive models.

### 4. Gap Analysis & Autonomous API Enhancement

The pipeline doesn't assume the test infrastructure already supports what the PRD requires. After the test plan is generated, the **Gap Analysis Agent** compares what the plan needs against what the networking helper APIs actually provide, checking five gap types:

- `missing_method` — a method that should exist but doesn't (e.g., VPNHelper needs `check_mtu()`)
- `missing_parameter` — a method exists but lacks a needed parameter (e.g., `establish_tunnel()` needs `mode="tcp"`)
- `missing_return_field` — a return type lacks a field the test needs
- `missing_tool` — a CLI tool (wget, wrk, dig, mtr) isn't wrapped by any module at all
- `missing_module` — an entirely new helper module is needed (e.g., `http_client.py` for wget)

When gaps are found, the **API Enhancement Agent** reads the actual source code of existing helper modules, generates the missing wrapper methods or creates entirely new modules, validates everything with `ast.parse`, verifies no existing code was accidentally deleted, writes the enhanced source, and regenerates API reference skills — all before the codegen stage runs.

This closes the automation loop: a PRD that requires new test capabilities triggers automatic enhancement of the test infrastructure itself. The helper APIs are subprocess wrappers following a consistent pattern (build CLI command → execute on topology node → parse output into dataclass), which is well within an LLM's capability to generate.

The gap policy is configurable: `pause` on critical gaps (wait for human review), `continue` best-effort, or `configurable` per severity level.

### 5. Self-Healing Test Repair + AST Validation

When generated tests fail due to code bugs (import errors, wrong assertions, fixture issues), the repair agent intercepts the failure before triage. It reads the error traceback and the test spec, generates a fix, validates the fix compiles, and the executor retries. This tight loop (executor → repair → executor) runs up to 2 times per failing test, converting many "test is broken" failures into actual test results.

Only failures classified as `test_bug` trigger repair. Product bugs, infrastructure issues, and configuration errors pass through to triage untouched.

**AST validation** is the safety gate used across all code-generating agents (CodeGen, Repair, API Enhance). Every piece of LLM-generated Python passes through `ast.parse()` before being written to disk. This catches syntax errors without executing code (no side effects, no imports, no subprocess calls). The API Enhance agent goes further: it compares class/function names before and after enhancement to ensure the LLM didn't accidentally delete existing code.

### 6. Checkpoint-Based Pipeline Resilience

The pipeline checkpoints state to disk after every stage. If it crashes at the code generation stage — due to an API timeout, a budget limit, or a network error — you resume from exactly where it stopped. No re-running ingestion, no re-extracting requirements, no re-generating the plan. The `pipeline_state.json` file tracks which stages completed, their artifacts, and their durations.

---

## Architecture

### Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLI / Configuration                             │
│  run | plan-only | execute-only | triage-only | --product | dry-run    │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│                      Pipeline Orchestrator                              │
│            DAG executor • checkpointing • budget enforcement            │
└──────────┬───────────────────────────────────────────┬──────────────────┘
           │                                           │
┌──────────▼──────────┐                   ┌────────────▼───────────┐
│   Model Router      │                   │   Skills Registry      │
│ Haiku/Sonnet/Opus   │                   │ skills/ → agents       │
│ cascade + budget    │                   │ progressive loading    │
└──────────┬──────────┘                   │ product overrides      │
           │                              │ auto-gen API refs      │
           │         ┌────────────────────┘
           │         │
   ┌───────┴───┬─────┴─┬─────────┬──────────┬───────┬───────┬───────┬───────┬───────┐
   │           │       │         │          │       │       │       │       │       │
   ▼           ▼       ▼         ▼          ▼       ▼       ▼       ▼       ▼       ▼
Ingest     Extract   Plan    Gap Anlys  API Enh  CodeGen Execute Repair Triage  Report
(Haiku)    (Sonnet)  (Opus)  (Sonnet)   (Sonnet) (Sonnet) (none) (Sonnet)(Opus) (Haiku)
   │           │       │         │          │       ��                      │
   └───skills──┴─skills─┴─skills──┴──skills──┴─skills┴──skills─────────skills┘
     categorization  vpn-protocols  cli-tools  enhancement  api-reference   diagnostic
     rules           l4-lb, l7-app  catalog    patterns     vpn-api, etc.   framework
                     security, perf
```

| Stage | Agent | Model | Input | Output |
|-------|-------|-------|-------|--------|
| **Ingest** | `IngestAgent` | Haiku | PDF, Markdown, HTML files | `IngestedDocument[]` — normalized markdown sections |
| **Extract** | `ExtractAgent` | Sonnet | Ingested documents | `RequirementSet` — tagged requirements with traceability IDs |
| **Plan** | `PlanAgent` | Opus | Requirement set | `TestPlan` — suites, test cases, steps, topology selection |
| **Gap Analysis** | `GapAnalysisAgent` | Sonnet | Test plan + API skills | `GapReport` — missing methods, params, tools, modules |
| **API Enhance** | `APIEnhanceAgent` | Sonnet | Gap report + source code | Enhanced/new helper modules + regenerated API skills |
| **CodeGen** | `CodeGenAgent` | Sonnet | Test plan + (now-complete) API | pytest files with `conftest.py` |
| **Execute** | `ExecutorAgent` | None | Generated test code + topology | `TestRunResult` — per-test pass/fail with logs |
| **Repair** | `RepairAgent` | Sonnet | Failed tests with tracebacks | Patched test code (max 2 retries) |
| **Triage** | `TriageAgent` | Opus | Test failures + logs | `TriageReport` — failure clusters, root causes, actions |
| **Report** | `ReportAgent` | Haiku | All prior artifacts | HTML report + Markdown summary |

### Model Routing & Cost Optimization

The model router maps each task type to an appropriate Claude model tier:

```
┌─────────────────────────────┬──────────┬───────────────────────────────┐
│ Task                        │ Model    │ Rationale                     │
├─────────────────────────────┼──────────┼───────────────────────────────┤
│ Document parsing            │ Haiku    │ Simple extraction             │
│ Requirement extraction      │ Sonnet   │ Domain understanding needed   │
│ Test plan generation        │ Opus     │ Highest-value reasoning       │
│ Test code generation        │ Sonnet   │ Good code gen, cost-effective │
│ Failure classification      │ Haiku    │ Simple categorization         │
│ Root cause analysis         │ Opus     │ Complex log/trace reasoning   │
│ Report summary              │ Haiku    │ Template filling              │
│ Test repair                 │ Sonnet   │ Targeted code fixes           │
│ Gap analysis                │ Sonnet   │ API surface comparison        │
│ API enhancement             │ Sonnet   │ Generate wrapper code         │
└─────────────────────────────┴──────────┴───────────────────────────────┘
```

**Cascade fallback:** If the assigned model's output fails Pydantic validation, the router automatically escalates one tier (Haiku → Sonnet → Opus, max depth 2). This catches cases where a cheaper model produces malformed JSON without defaulting every call to Opus.

**Budget enforcement:** Every LLM call is recorded to `generated/token_usage.jsonl`. A configurable hard cap (default $50/run) halts the pipeline before exceeding the budget, with a warning at 80%.

The router is built on an abstract `LLMProvider` interface, so adding OpenAI, Ollama, or vLLM backends requires implementing a single `async call()` method.

### Typed Artifact Contracts

All inter-agent communication flows through Pydantic v2 models:

```
IngestedDocument ──► RequirementSet ──► TestPlan ──► [pytest files]
                                                         │
            TriageReport ◄── TestRunResult ◄─────────────┘
                │
                ▼
          HTML Report + Markdown Summary
```

Key models and their relationships:

- **`Requirement`** — `req_id`, `category` (vpn/l4/l7/performance/security/ha), `priority` (P0-P3), `acceptance_criteria[]`, traced back to `source_doc_id` and `source_section`
- **`TestCaseSpec`** — `test_id`, `traced_req_ids[]` (links to requirements), `steps[]`, `topology` (which Containerlab topology to use), `tools[]` (iperf3, scapy, testssl, etc.)
- **`TestPlan`** — contains `suites[]` of `TestCaseSpec[]`, plus a `coverage_matrix` mapping `req_id → test_id[]`
- **`TestRunResult`** — `passed`/`failed`/`errored`/`skipped` counts, per-test `IndividualTestResult` with stdout, stderr, traceback, and captured artifacts
- **`TriageEntry`** — failure cluster with `root_cause_category`, `severity`, `confidence` (0.0-1.0), `evidence[]`, `affected_req_ids[]`, `recommended_action`

These models are serialized as JSON in the `generated/` directory tree, making every pipeline artifact inspectable and diffable.

### Self-Healing Repair Loop

```
                    ┌─────────────────────┐
                    │   ExecutorAgent      │
                    │  (runs pytest)       │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  Classify failure:   │
                    │  test_bug? product   │
                    │  bug? infra issue?   │
                    └─────────┬───────────┘
                              │
                 test_bug     │     product_bug / infra
              ┌───────────────┼───────────────┐
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │  RepairAgent     │             │  Pass to Triage  │
    │  (fix test code) │             │                  │
    └────────┬────────┘             └──────────────────┘
             │
    ┌────────▼────────┐
    │  Retry (max 2x) │──── still failing ──► Pass to Triage
    └────────┬────────┘
             │ fixed
             ▼
    Updated test results
```

The repair agent classifies failures using heuristics — `ImportError`, `SyntaxError`, `NameError`, and fixture-related errors indicate test code bugs. For these, it reads the failing test code and traceback, generates a fix via LLM, validates the fix compiles (`ast.parse`), writes it back, and signals the executor to retry.

### Checkpoint & Resume

```bash
# Pipeline crashes at codegen stage
agent-harness run --config config/harness.yaml
# ... ERROR at codegen, state saved to generated/pipeline_state.json

# Fix the issue, resume from where it stopped
agent-harness run --config config/harness.yaml --resume generated/
# Skips ingest, extract, plan (already completed), resumes at codegen
```

State is persisted as `generated/pipeline_state.json` after every stage:

```json
{
  "run_id": "a1b2c3d4e5f6",
  "current_stage": "codegen",
  "completed_stages": {
    "ingest": {"status": "success", "duration_seconds": 2.1, "artifact_paths": [...]},
    "extract": {"status": "success", "duration_seconds": 8.3, "artifact_paths": [...]},
    "plan": {"status": "success", "duration_seconds": 15.7, "artifact_paths": [...]}
  }
}
```

---

## Networking Test Infrastructure

### Containerlab Topologies

The harness uses [Containerlab](https://containerlab.dev) to spin up Docker-based network topologies for test execution. Four pre-built topologies cover different testing scenarios:

| Topology | Nodes | Use Case |
|----------|-------|----------|
| `vpn_basic` | vpn-gw, client, server | VPN protocol tests (WireGuard :51820, OpenVPN :1194, IKEv2 :500) |
| `l4_lb` | lb, client, backend1-4 | L4 load balancing with 4 backends (:80, :443) |
| `l7_proxy` | proxy, client, api-backend, static-backend | L7 routing, TLS termination, WAF (:80, :443, :8080) |
| `full_stack` | vpn-gw, lb, proxy, client1-2, api-server1-2, web-server1-2 | End-to-end: clients → VPN → LB → proxy → backends |

The test plan agent selects the appropriate topology per test case. The executor agent deploys it before running tests, waits for health checks to pass, and tears it down afterwards.

```
full_stack topology:

  client1 ──┐                    ┌── api-server1
  client2 ──┤── vpn-gw ── lb ── proxy ──┤── api-server2
             │                    ├── web-server1
             │                    └── web-server2
```

### Networking Helpers

Generated tests call clean Python APIs instead of raw shell commands. Each helper wraps infrastructure tools and executes commands on topology nodes:

**VPN Testing** (`src/networking/vpn.py`):
```python
vpn = VPNHelper(topology_manager)
tunnel = vpn.establish_tunnel(protocol="wireguard", client_node="client", gateway_node="vpn-gw")
assert tunnel.is_up, f"Tunnel failed: {tunnel.error}"
assert tunnel.handshake_time_ms < 5000

leak = vpn.check_dns_leak(client_node="client")
assert not leak.leak_detected, f"DNS leak: {leak.details}"

kill_switch_works = vpn.test_kill_switch(client_node="client", protocol="wireguard")
assert kill_switch_works
```

**Traffic Generation** (`src/networking/traffic.py`):
```python
tg = TrafficGenerator(topology_manager)
result = tg.iperf3(src="client", dst="server", protocol="tcp", duration=10, bandwidth="1G")
assert result.bandwidth_mbps >= 1000, f"Below threshold: {result.bandwidth_mbps}Mbps"

conn = tg.bulk_connections(src="client", dst="server", count=10000, port=80)
assert conn.failed == 0, f"{conn.failed} connections failed"
```

**Protocol Validation** (`src/networking/protocol.py`):
```python
pv = ProtocolValidator(topology_manager)
assert pv.verify_tls_version("10.0.1.1", expected="TLSv1.3")
assert pv.verify_no_tls_version("10.0.1.1", rejected="TLSv1.0")
assert pv.verify_pfs("10.0.1.1")
assert pv.verify_no_vulnerabilities("10.0.1.1")
```

**Packet Capture** (`src/networking/capture.py`):
```python
cap = PacketCapture(topology_manager, capture_dir="/tmp/captures")
cap_id = cap.start(node="client", interface="eth0", bpf_filter="port 443")
# ... generate traffic ...
result = cap.stop(cap_id)
analysis = cap.analyze(result.pcap_path, display_filter="tls")
assert analysis.packet_count > 0
```

---

## User Workflow

### Quick Start

```bash
# 1. Clone and install
git clone <repo-url> && cd agent-harness
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Place your PRD in the input directory
cp docs/examples/sample_vpn_prd.md docs/input/

# 4. Validate configuration (no LLM calls)
python3 -m src.cli run --dry-run

# 5. Run the full pipeline
python3 -m src.cli run

# 6. View the report
open generated/reports/report.html
```

### CLI Reference

```
agent-harness [--log-level DEBUG|INFO|WARNING|ERROR] <command>
```

**`run`** — Execute the full pipeline (ingest → report)
```bash
agent-harness run [--config CONFIG] [--docs-dir DIR] [--resume DIR] [--dry-run] [--product NAME]

  --config     Path to harness.yaml (default: config/harness.yaml)
  --docs-dir   Override input documents directory
  --resume     Resume from a checkpoint directory
  --dry-run    Validate config and inputs without executing
  --product    Load product-specific skills from skills/products/<NAME>/
```

**`plan-only`** — Stop after test plan generation
```bash
agent-harness plan-only [--config CONFIG] [--docs-dir DIR]
```

**`execute-only`** — Run pre-generated tests
```bash
agent-harness execute-only TEST_DIR [--config CONFIG] [--topology NAME]

  TEST_DIR     Directory containing generated test_*.py files
  --topology   Deploy this Containerlab topology before running
```

**`triage-only`** — Analyze existing test results
```bash
agent-harness triage-only RESULTS_PATH [--config CONFIG]

  RESULTS_PATH   Path to a TestRunResult JSON file
```

**`token-usage`** — Display cost breakdown
```bash
agent-harness token-usage [--run-dir DIR]
```

**`list-topologies`** — Show available network topologies
```bash
agent-harness list-topologies [--config CONFIG]
```

### Configuration

The harness is configured via `config/harness.yaml`. Key sections:

```yaml
# Model routing: which Claude model handles which task
models:
  tiers:
    haiku:  { id: "claude-haiku-4-5-20241022",  max_tokens: 4096  }
    sonnet: { id: "claude-sonnet-4-5-20250929",  max_tokens: 8192  }
    opus:   { id: "claude-opus-4-0-20250514",    max_tokens: 16384 }

  routing:
    document_parsing:       haiku      # Cheap model for simple extraction
    requirement_extraction: sonnet     # Domain understanding needed
    test_plan_generation:   opus       # Highest-value reasoning task
    test_code_generation:   sonnet     # Good code gen, cost-effective
    root_cause_analysis:    opus       # Complex failure reasoning

  cascade_on_validation_failure: true  # Escalate on parse failure
  budget:
    max_cost_usd: 50.00               # Hard stop if exceeded

# Gap analysis: detect and auto-fix missing test APIs
gap_analysis:
  enabled: true
  policy: configurable               # "pause", "continue", or "configurable"
  critical_action: pause              # Halt on critical gaps for review
  minor_action: continue              # Proceed past minor gaps

# Skills: domain expertise as markdown files
skills:
  skills_dir: "./skills"
  product: null                        # Override with --product flag
  auto_generate_api_skills: true       # Regen API refs from Python code
  max_skill_tokens_per_agent: 8000     # Token budget per agent

# Test execution
execution:
  timeout_per_test_seconds: 300
  parallel_workers: 4                  # pytest-xdist parallelism
  retry_flaky: 1                       # Retry failures once before triage

# Self-healing
repair:
  enabled: true
  max_attempts_per_test: 2

# Topology
topology:
  provider: containerlab
  default_topology: full_stack
  health_check_timeout_seconds: 120
```

---

## Project Structure

```
agent-harness/
├── config/
│   ├── harness.yaml                    # Master configuration (incl. skills config)
│   └── topologies/                     # Containerlab topology definitions
│       ├── vpn_basic.clab.yaml         #   VPN gateway + client + server
│       ├── l4_lb.clab.yaml             #   Load balancer + 4 backends
│       ├── l7_proxy.clab.yaml          #   L7 proxy + 2 backend pools
│       └── full_stack.clab.yaml        #   Full integration topology
│
├── skills/                             # ★ Domain expertise (markdown + YAML frontmatter)
│   ├── domains/                        #   Protocol & service knowledge
│   │   ├── vpn-protocols.md            #     WireGuard, OpenVPN, IKEv2 patterns
│   │   ├── l4-load-balancing.md        #     LB algorithms, NAT, conn tracking
│   │   └── l7-application.md           #     TLS, WAF, routing, session affinity
│   ├── test-patterns/                  #   Cross-cutting test strategies
│   │   ├── security-testing.md         #     OWASP, ciphers, PFS, leak detection
│   │   ├── performance-testing.md      #     iperf3, latency, scalability
│   │   ├── failover-testing.md         #     HA, split-brain, session persistence
│   │   └── negative-testing.md         #     Error injection, boundaries
│   ├── triage/                         #   Diagnostic frameworks
│   │   ├── diagnostic-framework.md     #     5-step RCA framework
│   │   └── failure-patterns.md         #     Error classification heuristics
│   ├── extraction/                     #   Requirement analysis rules
│   │   └── categorization-rules.md     #     Category & priority definitions
│   ├── tools/                          #   Infrastructure usage patterns
│   │   └── containerlab-ops.md         #     Topology selection rules
│   ├── api-reference/                  #   Auto-generated at pipeline start
│   │   ├── vpn-api.md                  #     ← from src/networking/vpn.py
│   │   ├── traffic-api.md              #     ← from src/networking/traffic.py
│   │   ├── protocol-api.md             #     ← from src/networking/protocol.py
│   │   └── capture-api.md              #     ← from src/networking/capture.py
│   └── products/                       #   Product-specific overrides
│       └── secureconnect/              #     (loaded with --product flag)
│
├── src/
│   ├── cli.py                          # Click CLI (run, plan-only, --product, etc.)
│   │
│   ├── orchestrator/
│   │   ├── pipeline.py                 # DAG executor + skill registry init
│   │   ├── state.py                    # Pipeline state machine
│   │   └── events.py                   # Inter-agent event bus
│   │
│   ├── router/
│   │   ├── model_router.py             # LLMProvider abstraction + routing
│   │   └── token_tracker.py            # Usage tracking + budget enforcement
│   │
│   ├── skills/                         # ★ Skills framework
│   │   ├── models.py                   #   Skill & SkillMetadata models
│   │   ├── loader.py                   #   File discovery + progressive loading
│   │   ├── registry.py                 #   Query by agent/domain/name/tag
│   │   ├── injector.py                 #   Compose skills into prompts (budgeted)
│   │   └── generator.py                #   Auto-gen API skills from Python AST
│   │
│   ├── agents/
│   │   ├── base.py                     # BaseAgent with skill-aware prompts
│   │   ├── ingest.py                   # Document parsing (PDF/MD/HTML)
│   │   ├── extract.py                  # Requirement extraction
│   │   ├── plan.py                     # Test plan design (Opus-powered)
│   │   ├── codegen.py                  # pytest code generation
│   │   ├── executor.py                 # Test runner + topology lifecycle
│   │   ├── repair.py                   # Self-healing for test code bugs
│   │   ├── triage.py                   # Failure clustering + root cause analysis
│   │   └── report.py                   # HTML + Markdown report generation
│   │
│   ├── artifacts/
│   │   ├── models.py                   # 20+ Pydantic models (inter-agent contracts)
│   │   ├── store.py                    # Filesystem-backed artifact persistence
│   │   └── validators.py              # Schema validation helpers
│   │
│   ├── topology/
│   │   ├── manager.py                  # Containerlab deploy/inspect/destroy
│   │   ├── inventory.py                # Dynamic node inventory with role inference
│   │   └── health.py                   # Node health checks
│   │
│   ├── networking/
│   │   ├── vpn.py                      # VPN helpers (WireGuard/OpenVPN/IKEv2)
│   │   ├── traffic.py                  # iperf3, scapy, HTTP, bulk connections
│   │   ├── protocol.py                 # testssl.sh, nmap wrappers
│   │   └── capture.py                  # tcpdump/tshark packet capture
│   │
│   └── reporting/
│       ├── generator.py                # Coverage matrix, category summaries
│       └── templates/
│           ├── report.html.j2          # Full HTML report template
│           └── summary.md.j2           # Markdown summary template
│
├── tests/                              # 52 tests covering all components
├── docs/
│   ├── input/                          # Drop PRDs here
│   ├── slides.html                     # Architecture presentation
│   └── examples/
│       └── sample_vpn_prd.md           # SecureConnect VPN Gateway PRD
│
├── generated/                          # Runtime output (gitignored)
│   ├── pipeline_state.json
│   ├── token_usage.jsonl
│   ├── requirements/
│   ├── test_plans/
│   ├── test_code/
│   ├── results/
│   ├── triage/
│   └── reports/
│
└── pyproject.toml
```

---

## Extending the Harness

### Adding Domain Skills (No Python Required)

Create a markdown file in `skills/` with YAML frontmatter. The skill is auto-discovered at the next pipeline run.

**Example: Adding SD-WAN test expertise**

```markdown
# skills/domains/sdwan.md
---
name: sdwan-testing
description: SD-WAN overlay and underlay test patterns
domain: sdwan
applies_to: [plan, codegen, triage]
priority: 2
tags: [sdwan, overlay, underlay, ipsec, vxlan]
---

## SD-WAN Overlay Testing
- Verify VXLAN encapsulation between sites
- Test IPSec tunnel failover between WAN links
- Measure overlay throughput vs underlay capacity
...
```

The plan agent will now include SD-WAN test patterns when generating plans for requirements that involve SD-WAN. The triage agent will use it for failure classification. No Python code changes needed.

### Product-Specific Customization

Create a product directory and run with `--product`:

```bash
# Create product-specific skills
mkdir -p skills/products/my-firewall/
cat > skills/products/my-firewall/product-context.md << 'EOF'
---
name: product-context
description: MyFirewall-specific test priorities and known issues
applies_to: [plan, triage]
priority: 0
---

## Known Issues
- Zone-based policy evaluation has a 50ms latency spike under 10K rules
- HA failover takes 5s (not 3s) when connection table exceeds 50K entries

## Test Priorities
- Focus on zone-based policy correctness (high customer impact)
- Always test with realistic rule counts (5K, 10K, 50K rules)
EOF

# Run pipeline with product context
agent-harness run --product my-firewall
```

### Adding a New LLM Provider

Implement the `LLMProvider` interface — one async method:

```python
class OllamaProvider(LLMProvider):
    async def call(self, model_id, system, messages, max_tokens) -> LLMResponse:
        # Call your backend, return LLMResponse(text, input_tokens, output_tokens, model_id)
        ...
```

The router, token tracker, skills injector, and all agents work unchanged.

### Adding a New Topology

Create a `.clab.yaml` file in `config/topologies/`. Auto-discovered via `list-topologies`. Add a companion skill in `skills/tools/` describing when to use it:

```yaml
# config/topologies/dmz.clab.yaml
name: dmz
topology:
  nodes:
    external-fw:
      kind: linux
      image: firewall:latest
    dmz-server:
      kind: linux
      image: test-server:latest
  links:
    - endpoints: ["external-fw:eth1", "dmz-server:eth1"]
```

### Sharing Skill Packs

Skills are plain files in git. Teams can share skill libraries across projects:

```bash
# Import a community skill pack
git clone https://github.com/team/5g-qa-skills.git skills/domains/5g/

# The pipeline automatically discovers and loads them
agent-harness run
```
