# CLAUDE.md — Agent Harness Project Context

## What This Project Is

An autonomous QA pipeline for VPN & L4-L7 networking products. It takes PRDs as input and produces complete QA reports with no human intervention between stages.

**9-stage pipeline**: Ingest → Extract → Plan → Gap Analysis → API Enhance → CodeGen → Execute → Triage → Report

## Quick Reference

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...

# Run tests (always do this after changes)
python3 -m pytest tests/ -v

# Dry run (validates config without LLM calls)
python3 -m src.cli run --dry-run

# Full pipeline
python3 -m src.cli run --docs-dir docs/input/

# With product-specific skills
python3 -m src.cli run --product secureconnect
```

## Architecture Overview

```
CLI → Pipeline Orchestrator (checkpointed DAG)
        ├── Model Router (Haiku/Sonnet/Opus with cascade fallback)
        ├── Skills Registry (markdown files → agent prompts)
        └── Agents (10 agents across 9 stages)
```

### Key Directories

| Path | Purpose |
|------|---------|
| `src/agents/` | 10 agents (ingest, extract, plan, gap_analysis, api_enhance, codegen, executor, repair, triage, report) |
| `src/skills/` | Skills framework (loader, registry, injector, generator) |
| `src/router/` | Model routing + token tracking |
| `src/orchestrator/` | Pipeline DAG executor + state machine |
| `src/artifacts/` | Pydantic models (inter-agent contracts) + filesystem store |
| `src/networking/` | VPN, traffic, protocol, capture helpers (subprocess wrappers) |
| `src/reporting/` | Jinja2 report generator + templates |
| `src/topology/` | Containerlab lifecycle management |
| `skills/` | Domain expertise as markdown files (auto-discovered) |
| `config/` | harness.yaml + Containerlab topology YAMLs |
| `tests/` | 52 tests across 7 test files |

### Model Routing

| Task | Model | Why |
|------|-------|-----|
| document_parsing | Haiku | Simple extraction |
| requirement_extraction | Sonnet | Domain understanding |
| test_plan_generation | Opus | Highest-value reasoning |
| gap_analysis | Sonnet | API surface comparison |
| api_enhancement | Sonnet | Generate wrapper code |
| test_code_generation | Sonnet | Code gen |
| root_cause_analysis | Opus | Complex failure reasoning |
| report_summary | Haiku | Template filling |
| test_repair | Sonnet | Targeted fixes |

## Code Conventions

### Agent Pattern
Every agent extends `BaseAgent` and declares three class attributes:
```python
class SomeAgent(BaseAgent):
    agent_name = "some"                    # Used for logging + skill matching
    default_task_type = "some_task"        # Maps to models.routing config
    core_system_prompt = "..."             # Slim role + output format ONLY
```

Domain knowledge goes in `skills/*.md` files, NOT in Python prompts. The `_build_system_prompt()` method in BaseAgent composes core_prompt + matched skills automatically.

Agents call `self.llm_call(user_content=...)` — do NOT pass `system=` unless overriding skill injection for a specific call.

### Skills Pattern
Skills are markdown files with YAML frontmatter in `skills/`. Format:
```markdown
---
name: skill-name
description: One-line description
applies_to: [plan, codegen, triage]   # Which agents get this skill
priority: 1                            # Lower = loaded first
---
Content here (injected into agent system prompt)
```

`applies_to: []` (empty) means the skill applies to ALL agents. API reference skills in `skills/api-reference/` are auto-generated from Python source via AST — don't edit them manually.

### Networking Helper Pattern
All helpers follow this consistent pattern:
```python
class SomeHelper:
    def __init__(self, topology_manager): self.topo = topology_manager
    def _exec(self, node, cmd, timeout=60): ...  # Run on topology node
    def some_op(self, node="client", ...) -> SomeResult:
        cmd = "cli-tool --flag value"
        output = self._exec(node, cmd)
        return self._parse(output)  # Returns a dataclass
```

Return types are always dataclasses with `error: str = ""` field and a `success` property.

### AST Validation
All LLM-generated Python code MUST pass `ast.parse()` before being written to disk. This applies to: CodeGen, Repair, and API Enhance agents. The API Enhance agent additionally verifies no existing class/function names were removed.

### Artifact Models
All inter-agent data flows through Pydantic v2 models in `src/artifacts/models.py`. When adding a new stage or modifying agent outputs, define the model there first.

### Pipeline Stage Registration
To add a new pipeline stage:
1. Add enum value in `PipelineStage` (src/artifacts/models.py)
2. Add to `STAGE_ORDER` list (src/orchestrator/state.py)
3. Add `_get_agent()` case (src/orchestrator/pipeline.py)
4. Create the agent file in `src/agents/`
5. Add routing entry in `config/harness.yaml` under `models.routing`

## What NOT To Do

- Don't hardcode domain knowledge in agent SYSTEM_PROMPTs — put it in skills/*.md
- Don't manually write `skills/api-reference/` files — they're auto-generated
- Don't add `system=` parameter to `self.llm_call()` unless intentionally bypassing skills
- Don't modify `generated/` contents — it's pipeline output, gitignored
- Don't skip `ast.parse()` validation on any LLM-generated code path

## Current State (as of initial commit)

- All 9 pipeline stages implemented with thin-to-deep agent logic
- Skills framework fully wired: 12 skill files, auto-gen API refs, product overrides
- Gap analysis detects 5 gap types including missing_tool and missing_module
- API enhance agent can create entirely new helper modules from scratch
- 4 Containerlab topologies: vpn_basic, l4_lb, l7_proxy, full_stack
- 52 tests passing
- Not yet tested end-to-end with a live Anthropic API key

## Next Steps / Open Work

- End-to-end run with live API key against sample_vpn_prd.md
- Tune agent prompts based on real LLM output quality
- Build Docker images for topology nodes (vpn-gateway, test-client, test-server)
- Add `--dry-run` to show skill injection (which skills loaded per agent)
- CI/CD integration (GitHub Actions workflow)
- Expand test coverage for gap_analysis and api_enhance agents with mocked LLM
