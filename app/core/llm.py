"""LLM service: HydraGPT (OpenAI-compatible) client + Jinja2 template rendering."""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import jinja2
from openai import OpenAI

_T = TypeVar("_T")

# HydraGPT proxy (OpenAI-compatible endpoint). Override via LLM_BASE_URL if needed.
DEFAULT_BASE_URL = "https://hydragpt.ru/v1"
# Default model; full list at /models (kimi-k2p7, minimax-m3, nemotron-3-ultra, ...).
DEFAULT_MODEL = "kimi-k2p6"


class LLMService:
    """HydraGPT-based LLM service (OpenAI-compatible) with Jinja2 template support."""

    def __init__(
        self,
        api_key: str,
        template_dir: Path | str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        )
        self._model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)

        if template_dir is None:
            template_dir = Path(__file__).resolve().parent.parent.parent / "data" / "prompts"

        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=False,
        )

    @property
    def model(self) -> str:
        return self._model

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

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and status >= 500:
            return True
        msg = str(exc).lower()
        return any(s in msg for s in ["timeout", "timed out", "temporarily", "try again", "service unavailable"])

    async def _call_with_timeout_and_retry(
        self,
        fn: Callable[[], _T],
        *,
        timeout_sec: int = 20,
        retries: int = 1,
        retry_delay_sec: float = 0.7,
    ) -> _T:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_sec)
            except asyncio.TimeoutError as e:
                last_exc = e
                transient = True
            except Exception as e:
                last_exc = e
                transient = self._is_transient_error(e)

            if attempt < retries and transient:
                await asyncio.sleep(retry_delay_sec)
                continue
            assert last_exc is not None
            raise last_exc

    async def generate_advice_async(
        self,
        template_name: str,
        context: dict[str, Any],
    ) -> tuple[str, int, int, int]:
        """
        Render a Jinja2 template and call the LLM to generate advice asynchronously.
        Returns (result_text, latency_ms, prompt_chars, response_chars)
        """
        context = self._normalize_context(context)
        template = self._env.get_template(template_name)
        prompt = template.render(**context)
        
        start_time = time.perf_counter()
        
        def _call():
            return self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

        timeout_sec = int(os.getenv("LLM_TIMEOUT_SEC", "20"))
        response = await self._call_with_timeout_and_retry(
            _call,
            timeout_sec=timeout_sec,
            retries=1,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        result_text = response.choices[0].message.content or ""

        return result_text, latency_ms, len(prompt), len(result_text)

    def generate_advice(
        self,
        template_name: str,
        context: dict[str, Any],
    ) -> str:
        # Keeping for backward compatibility if needed, but we'll use async version
        context = self._normalize_context(context)
        template = self._env.get_template(template_name)
        prompt = template.render(**context)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return response.choices[0].message.content or ""

    async def generate_sim_response_async(
        self,
        simulation_context: str,
        history: list[dict[str, str]],
        user_message: str,
        role_name: str | None = None,
        opponent_style: str | None = None,
        swearing_allowed: str | None = None,
    ) -> tuple[str, int, int, int]:
        context = {
            "role_name": role_name or "Оппонент",
            "context": simulation_context,
            "user_message": user_message,
            "history": history,
            "opponent_style": opponent_style or "calm_incident_manager",
            "swearing_allowed": swearing_allowed or "no",
            "simulation_context": simulation_context,
            "message": user_message,
        }
        template = self._env.get_template("simulator.j2")
        prompt = template.render(**context)

        temperature = 0.6
        if context.get("opponent_style") == "partner_hot_scandal":
            temperature = 0.9

        start_time = time.perf_counter()
        
        def _call():
            return self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )

        timeout_sec = int(os.getenv("LLM_TIMEOUT_SEC", "20"))
        response = await self._call_with_timeout_and_retry(
            _call,
            timeout_sec=timeout_sec,
            retries=1,
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        result_text = response.choices[0].message.content or ""

        return result_text, latency_ms, len(prompt), len(result_text)

    def generate_sim_response(
        self,
        simulation_context: str,
        history: list[dict[str, str]],
        user_message: str,
        role_name: str | None = None,
        opponent_style: str | None = None,
        swearing_allowed: str | None = None,
    ) -> str:
        context = {
            "role_name": role_name or "Оппонент",
            "context": simulation_context,
            "user_message": user_message,
            "history": history,
            "opponent_style": opponent_style or "calm_incident_manager",
            "swearing_allowed": swearing_allowed or "no",
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

        timeout_sec = int(os.getenv("LLM_TIMEOUT_SEC", "20"))
        return await self._call_with_timeout_and_retry(
            _call,
            timeout_sec=timeout_sec,
            retries=1,
        )
