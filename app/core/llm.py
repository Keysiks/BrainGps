"""LLM service: Groq client + Jinja2 template rendering."""

import asyncio
from pathlib import Path
from typing import Any

import jinja2
from groq import Groq


class LLMService:
    """Groq-based LLM service with Jinja2 template support."""

    def __init__(
        self,
        api_key: str,
        template_dir: Path | str | None = None,
        model: str = "llama-3.3-70b-versatile",
    ) -> None:
        self._client = Groq(api_key=api_key)
        self._model = model

        if template_dir is None:
            template_dir = Path(__file__).resolve().parent.parent.parent / "data" / "prompts"

        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=False,
        )

    @staticmethod
    def _normalize_context(context: dict[str, Any]) -> dict[str, Any]:
        """Normalize config.reference (list -> str) for template compatibility."""
        context = context.copy()
        config = context.get("config")
        if config and isinstance(config, dict):
            ref = config.get("reference")
            if isinstance(ref, list):
                config = {**config, "reference": "\n".join(str(x) for x in ref)}
                context["config"] = config
        return context

    def generate_advice(
        self,
        template_name: str,
        context: dict[str, Any],
    ) -> str:
        """
        Render a Jinja2 template and call Groq to generate advice.

        Args:
            template_name: Name of the template file (e.g. 'work_template.j2').
            context: Dictionary passed to the template. Must include:
                - config: llm_config from the strategy node (strategy_name, rules, reference)
                - inputs: User inputs from input_fields
                - ui_description: Optional description for the strategy

        Returns:
            Generated text from the LLM.
        """
        context = self._normalize_context(context)
        template = self._env.get_template(template_name)
        prompt = template.render(**context)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return response.choices[0].message.content or ""

    def generate_sim_response(
        self,
        simulation_context: str,
        history: list[dict[str, str]],
        user_message: str,
        role_name: str | None = None,
        opponent_style: str | None = None,
        swearing_allowed: str | None = None,
    ) -> str:
        """
        Generate opponent reply for the roleplay simulator.

        Args:
            simulation_context: Formatted context (user's inputs from the strategy step).
            history: List of {"role": "user"|"opponent", "text": "..."} for conversation.
            user_message: The user's last message.

        Returns:
            Short reply from the opponent's perspective (1-2 sentences).
        """
        context = {
            # Variables expected by data/prompts/simulator.j2
            "role_name": role_name or "Оппонент",
            "context": simulation_context,
            "user_message": user_message,
            "history": history,
            "opponent_style": opponent_style or "calm_incident_manager",
            "swearing_allowed": swearing_allowed or "no",
            # Backwards-compatible aliases (in case template changes)
            "simulation_context": simulation_context,
            "message": user_message,
        }
        template = self._env.get_template("simulator.j2")
        prompt = template.render(**context)

        temperature = 0.6
        if context.get("opponent_style") == "partner_hot_scandal":
            temperature = 0.9

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def generate_coach_hint(
        self,
        context: str,
        strategy_name: str | None,
        strategy_rules: list[str] | None,
        history: list[dict],
        last_user_message: str | None,
        last_opponent_message: str | None,
    ) -> str:
        template = self._env.get_template("coach_template.j2")
        prompt = template.render(
            strategy_name=strategy_name,
            strategy_rules=strategy_rules or [],
            context=context,
            history=history,
            last_user_message=last_user_message,
            last_opponent_message=last_opponent_message,
        )

        def _call() -> str:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
            )
            return response.choices[0].message.content or ""

        return await asyncio.to_thread(_call)
