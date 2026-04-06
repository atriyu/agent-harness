"""Test Executor Agent: runs generated pytest tests and collects results.

This is a non-LLM agent -- it drives pytest execution, manages topology
lifecycle, and parses results. Integrates with the repair agent for
self-healing on test code bugs.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import (
    IndividualTestResult,
    RepairAttempt,
    TestRunResult,
    TestStatus,
)

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    agent_name = "executor"
    default_task_type = ""  # No LLM calls

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]
        config = inputs["config"]
        output_dir = Path(config["harness"]["output_dir"])
        test_code_dir = output_dir / "test_code"
        results_dir = output_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        if not test_code_dir.exists() or not list(test_code_dir.glob("test_*.py")):
            raise FileNotFoundError(f"No test files found in {test_code_dir}")

        exec_config = config.get("execution", {})
        timeout = exec_config.get("timeout_per_test_seconds", 300)
        workers = exec_config.get("parallel_workers", 1)
        retry_flaky = exec_config.get("retry_flaky", 1)
        collect_pcaps = exec_config.get("collect_pcaps", False)
        collect_logs = exec_config.get("collect_container_logs", False)

        # Deploy topology if configured
        topology_deployed = False
        topo_config = config.get("topology", {})

        if topo_config.get("provider") == "containerlab":
            topology_deployed = await self._deploy_topology(topo_config, output_dir)

        # Run tests
        run_id = uuid.uuid4().hex[:12]
        json_report_path = results_dir / f"report_{run_id}.json"

        test_results, duration = await self._run_pytest(
            test_code_dir, json_report_path, timeout, workers, output_dir,
        )

        # Retry failures once if configured
        if retry_flaky > 0:
            failed_nodeids = [
                t.test_id for t in test_results
                if t.status in (TestStatus.FAILED, TestStatus.ERROR)
            ]
            if failed_nodeids:
                self.logger.info("Retrying %d failed tests...", len(failed_nodeids))
                retry_report = results_dir / f"retry_{run_id}.json"
                retry_results, retry_dur = await self._run_pytest_selective(
                    test_code_dir, retry_report, timeout, failed_nodeids, output_dir,
                )
                duration += retry_dur
                # Merge: if a retry passed, update the result
                retry_map = {r.test_id: r for r in retry_results}
                for i, tr in enumerate(test_results):
                    if tr.test_id in retry_map and retry_map[tr.test_id].status == TestStatus.PASSED:
                        test_results[i] = retry_map[tr.test_id]

        # Invoke repair agent for test_bug failures
        repair_attempts = await self._run_repair_loop(test_results, config, store)

        # Collect container logs if configured
        if collect_logs and topology_deployed:
            self._collect_container_logs(topo_config, results_dir, run_id)

        # Destroy topology if configured
        if topology_deployed and not topo_config.get("keep_alive_after_run", False):
            self._destroy_topology(topo_config)

        # Build final result
        passed = sum(1 for t in test_results if t.status == TestStatus.PASSED)
        failed = sum(1 for t in test_results if t.status == TestStatus.FAILED)
        errored = sum(1 for t in test_results if t.status == TestStatus.ERROR)
        skipped = sum(1 for t in test_results if t.status == TestStatus.SKIPPED)

        run_result = TestRunResult(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
            topology_used=topo_config.get("default_topology", "none"),
            total=len(test_results),
            passed=passed,
            failed=failed,
            errored=errored,
            skipped=skipped,
            duration_seconds=duration,
            test_results=test_results,
            repair_attempts=repair_attempts,
        )

        path = store.save("results", f"run_{run_id}.json", run_result)
        self.logger.info(
            "Results: %d passed, %d failed, %d errors, %d skipped (%.1fs)",
            passed, failed, errored, skipped, duration,
        )

        return {"artifact_paths": [str(path)], "run_result": run_result}

    async def _deploy_topology(self, topo_config: dict, output_dir: Path) -> bool:
        """Deploy Containerlab topology. Returns True if successful."""
        try:
            from src.topology.manager import TopologyManager
            from src.topology.inventory import build_inventory
            from src.topology.health import wait_for_topology_healthy

            topo_dir = topo_config.get("topologies_dir", "config/topologies")
            topo_name = topo_config.get("default_topology", "full_stack")
            health_timeout = topo_config.get("health_check_timeout_seconds", 120)

            manager = TopologyManager(topo_dir)
            info = manager.deploy(topo_name)
            inventory = build_inventory(info)

            # Wait for health
            health = wait_for_topology_healthy(inventory, timeout_seconds=health_timeout)
            if not health.all_healthy:
                self.logger.warning("Topology not fully healthy, proceeding anyway")

            return True

        except Exception as e:
            self.logger.warning("Topology deployment failed: %s. Running tests without topology.", e)
            return False

    def _destroy_topology(self, topo_config: dict) -> None:
        """Destroy the topology after test run."""
        try:
            from src.topology.manager import TopologyManager
            topo_dir = topo_config.get("topologies_dir", "config/topologies")
            topo_name = topo_config.get("default_topology", "full_stack")
            manager = TopologyManager(topo_dir)
            manager.destroy(topo_name)
        except Exception as e:
            self.logger.warning("Topology destruction failed: %s", e)

    def _collect_container_logs(
        self, topo_config: dict, results_dir: Path, run_id: str,
    ) -> None:
        """Collect logs from all topology containers."""
        try:
            logs_dir = results_dir / f"logs_{run_id}"
            logs_dir.mkdir(exist_ok=True)

            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}", "--filter", "label=containerlab"],
                capture_output=True, text=True, timeout=10,
            )
            for container in result.stdout.strip().split("\n"):
                if not container:
                    continue
                log_result = subprocess.run(
                    ["docker", "logs", container],
                    capture_output=True, text=True, timeout=30,
                )
                (logs_dir / f"{container}.log").write_text(
                    log_result.stdout + "\n---STDERR---\n" + log_result.stderr
                )
        except Exception as e:
            self.logger.warning("Failed to collect container logs: %s", e)

    async def _run_pytest(
        self,
        test_code_dir: Path,
        json_report_path: Path,
        timeout: int,
        workers: int,
        output_dir: Path,
    ) -> tuple[list[IndividualTestResult], float]:
        """Run full pytest suite."""
        cmd = [
            sys.executable, "-m", "pytest",
            str(test_code_dir),
            "--json-report",
            f"--json-report-file={json_report_path}",
            f"--timeout={timeout}",
            "-v",
            "--tb=long",
        ]
        if workers > 1:
            cmd.extend(["-n", str(workers)])

        self.logger.info("Running: %s", " ".join(cmd))

        start = datetime.now(timezone.utc)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout * 10,
            cwd=str(output_dir.parent),
        )
        duration = (datetime.now(timezone.utc) - start).total_seconds()

        self.logger.info("pytest exit code: %d (%.1fs)", result.returncode, duration)
        return self._parse_json_report(json_report_path, result), duration

    async def _run_pytest_selective(
        self,
        test_code_dir: Path,
        json_report_path: Path,
        timeout: int,
        node_ids: list[str],
        output_dir: Path,
    ) -> tuple[list[IndividualTestResult], float]:
        """Re-run specific test node IDs."""
        cmd = [
            sys.executable, "-m", "pytest",
            "--json-report",
            f"--json-report-file={json_report_path}",
            f"--timeout={timeout}",
            "-v", "--tb=long",
        ] + node_ids

        start = datetime.now(timezone.utc)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout * 10,
            cwd=str(output_dir.parent),
        )
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        return self._parse_json_report(json_report_path, result), duration

    async def _run_repair_loop(
        self,
        test_results: list[IndividualTestResult],
        config: dict,
        store,
    ) -> list[RepairAttempt]:
        """Run the repair agent on test_bug failures if repair is enabled."""
        repair_config = config.get("repair", {})
        if not repair_config.get("enabled", True):
            return []

        # Only import repair agent if needed
        from src.agents.repair import RepairAgent

        failures_with_test_bugs = [
            t for t in test_results
            if t.status in (TestStatus.ERROR, TestStatus.FAILED)
            and t.traceback
        ]

        if not failures_with_test_bugs:
            return []

        # Instantiate repair agent with same router/store
        repair = RepairAgent(self.router, store, config)
        result = await repair.run({
            "store": store,
            "config": config,
            "state": None,
            "output_dir": Path(config["harness"]["output_dir"]),
        })

        return result.get("repairs", [])

    def _parse_json_report(
        self, report_path: Path, proc_result: subprocess.CompletedProcess,
    ) -> list[IndividualTestResult]:
        """Parse the pytest-json-report output into our model."""
        results = []

        if report_path.exists():
            try:
                report = json.loads(report_path.read_text())
                for test in report.get("tests", []):
                    nodeid = test.get("nodeid", "unknown")
                    outcome = test.get("outcome", "error")

                    status_map = {
                        "passed": TestStatus.PASSED,
                        "failed": TestStatus.FAILED,
                        "error": TestStatus.ERROR,
                        "skipped": TestStatus.SKIPPED,
                    }

                    call = test.get("call", {})
                    setup = test.get("setup", {})

                    results.append(IndividualTestResult(
                        test_id=nodeid,
                        status=status_map.get(outcome, TestStatus.ERROR),
                        duration_seconds=call.get("duration", 0.0),
                        stdout=call.get("stdout", "") or "",
                        stderr=call.get("stderr", "") or "",
                        traceback=call.get("longrepr", None) or setup.get("longrepr", None),
                    ))
                return results
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.warning("Failed to parse json report: %s", e)

        # Fallback
        results.append(IndividualTestResult(
            test_id="pytest-run",
            status=TestStatus.PASSED if proc_result.returncode == 0 else TestStatus.ERROR,
            stdout=proc_result.stdout[:5000],
            stderr=proc_result.stderr[:5000],
        ))
        return results
