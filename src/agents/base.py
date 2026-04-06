"""Abstract base agent class that standardizes LLM interaction, logging, and artifact handling.

Supports optional skill injection: when a SkillRegistry is provided, the agent's
system prompt is composed from its core_system_prompt + matched domain skills.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from src.artifacts.store import ArtifactStore
from src.router.model_router import ModelRouter


class BaseAgent(ABC):
    """Base class for all pipeline agents.

    Each agent declares:
    - `agent_name`: used for logging and skill matching
    - `default_task_type`: maps to the model routing config
    - `core_system_prompt`: minimal role definition + output format (stays in Python)

    Domain expertise is injected via skills at runtime.
    """

    agent_name: str = "base"
    default_task_type: str = ""
    core_system_prompt: str = ""

    def __init__(
        self,
        router: ModelRouter,
        store: ArtifactStore,
        config: dict,
        skill_registry=None,
    ):
        self.router = router
        self.store = store
        self.config = config
        self.skill_registry = skill_registry
        self.logger = logging.getLogger(f"agent.{self.agent_name}")

    @abstractmethod
    async def run(self, inputs: Any) -> Any:
        """Execute the agent's primary task. Inputs and outputs are typed per agent."""
        ...

    def _build_system_prompt(self) -> str:
        """Compose the full system prompt from core prompt + matched skills.

        If no skill_registry is available, falls back to core_system_prompt.
        """
        from src.skills.injector import build_prompt_with_skills

        max_tokens = self.config.get("skills", {}).get("max_skill_tokens_per_agent", 8000)

        return build_prompt_with_skills(
            agent_name=self.agent_name,
            core_prompt=self.core_system_prompt,
            registry=self.skill_registry,
            max_skill_tokens=max_tokens,
        )

    async def llm_call(
        self,
        user_content: str,
        system: str = "",
        task_type: str | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> Any:
        """Standardized LLM call through the model router.

        If `system` is not provided, uses `_build_system_prompt()` which
        composes the core prompt with matched skills.
        """
        if not system:
            system = self._build_system_prompt()

        task = task_type or self.default_task_type
        messages = [{"role": "user", "content": user_content}]
        return await self.router.call(
            task_type=task,
            system=system,
            messages=messages,
            response_model=response_model,
        )
