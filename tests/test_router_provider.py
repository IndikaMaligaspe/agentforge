"""
Tests for TODO-9: query_router_node.py.j2 and requirements.txt.j2 vendor-neutrality.

Covers both the OpenAI default path (byte-identity) and the Anthropic path
(correct imports and constructor kwarg).
"""
import ast
import subprocess
import warnings

import pytest
import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined

from agentforge.schema.models import LLMModel, ProjectConfig
from agentforge.engine.renderer import TemplateRenderer


def _load_config(extra_workflow: dict | None = None) -> ProjectConfig:
    """Load full.yaml and optionally override workflow fields."""
    with open("tests/fixtures/full.yaml") as f:
        data = yaml.safe_load(f)
    if extra_workflow:
        data["workflow"].update(extra_workflow)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return ProjectConfig(**data)


def _render_router(renderer: TemplateRenderer, ctx: dict) -> str:
    tmpl = renderer._env.get_template("query_router_node.py.j2")
    return tmpl.render(**ctx)


def _render_requirements(renderer: TemplateRenderer, ctx: dict) -> str:
    tmpl = renderer._env.get_template("requirements.txt.j2")
    return tmpl.render(**ctx)


def _render_original_router(ctx: dict) -> str:
    """Render the router template from the git HEAD version for byte-identity comparison."""
    orig_bytes = subprocess.check_output(
        ["git", "show", "HEAD:agentforge/templates/query_router_node.py.j2"]
    )
    env = Environment(
        loader=BaseLoader(),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.from_string(orig_bytes.decode("utf-8")).render(**ctx)


def _render_original_requirements(ctx: dict) -> str:
    """Render the requirements template from the git HEAD version for byte-identity comparison."""
    orig_bytes = subprocess.check_output(
        ["git", "show", "HEAD:agentforge/templates/requirements.txt.j2"]
    )
    env = Environment(
        loader=BaseLoader(),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.from_string(orig_bytes.decode("utf-8")).render(**ctx)


class TestRouterDefaultProviderOpenAI:
    """Tests for the default openai provider path — must be byte-identical to HEAD."""

    def test_router_default_provider_openai_byte_identity(self):
        """
        Rendering query_router_node.py.j2 with the default openai provider must
        produce output byte-identical to what the HEAD template produces.
        """
        config = _load_config()
        assert config.workflow.router_llm_provider == "openai"

        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)

        rendered = _render_router(renderer, ctx)
        original = _render_original_router(ctx)

        assert rendered == original, (
            "query_router_node.py rendered with openai provider is NOT byte-identical "
            "to the HEAD template output"
        )

    def test_router_openai_imports_chatopenai(self):
        """The openai path must import ChatOpenAI from langchain_openai."""
        config = _load_config()
        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_router(renderer, ctx)

        assert "from langchain_openai import ChatOpenAI" in rendered
        assert "ChatOpenAI(model=" in rendered
        assert "ChatAnthropic" not in rendered
        assert "langchain_anthropic" not in rendered

    def test_router_openai_parses_as_valid_python(self):
        """The rendered openai router must be valid Python."""
        config = _load_config()
        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_router(renderer, ctx)
        ast.parse(rendered)  # raises SyntaxError on failure

    def test_requirements_openai_byte_identity(self):
        """
        Rendering requirements.txt.j2 with the default openai provider must
        produce output byte-identical to what the HEAD template produces.
        """
        config = _load_config()
        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)

        rendered = _render_requirements(renderer, ctx)
        original = _render_original_requirements(ctx)

        assert rendered == original, (
            "requirements.txt rendered with openai provider is NOT byte-identical "
            "to the HEAD template output"
        )

    def test_requirements_openai_no_langchain_anthropic(self):
        """The openai path must NOT include langchain-anthropic in requirements."""
        config = _load_config()
        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_requirements(renderer, ctx)
        assert "langchain-anthropic" not in rendered


class TestRouterAnthropicProvider:
    """Tests for the anthropic provider path."""

    def test_router_anthropic_provider_renders_chatanthropic(self):
        """
        Rendering query_router_node.py.j2 with router_llm_provider=anthropic must
        import ChatAnthropic and use model_name= (not model=).
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            config = _load_config(
                extra_workflow={
                    "router_llm_provider": "anthropic",
                    "router_llm_model": LLMModel.CLAUDE_3_HAIKU.value,
                }
            )

        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_router(renderer, ctx)

        assert "from langchain_anthropic import ChatAnthropic" in rendered
        assert "ChatAnthropic(model_name=" in rendered
        assert "ChatOpenAI" not in rendered
        assert "langchain_openai" not in rendered

    def test_router_anthropic_parses_as_valid_python(self):
        """The rendered anthropic router must be valid Python."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            config = _load_config(
                extra_workflow={
                    "router_llm_provider": "anthropic",
                    "router_llm_model": LLMModel.CLAUDE_3_HAIKU.value,
                }
            )

        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_router(renderer, ctx)
        ast.parse(rendered)  # raises SyntaxError on failure

    def test_requirements_anthropic_has_langchain_anthropic(self):
        """The anthropic path must include langchain-anthropic>=0.1.0,<0.4.0."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            config = _load_config(
                extra_workflow={
                    "router_llm_provider": "anthropic",
                    "router_llm_model": LLMModel.CLAUDE_3_HAIKU.value,
                }
            )

        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_requirements(renderer, ctx)

        assert "langchain-anthropic>=0.1.0,<0.4.0" in rendered

    def test_router_anthropic_model_name_kwarg_correct(self):
        """The Anthropic instantiation must use model_name= with the configured model value."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            config = _load_config(
                extra_workflow={
                    "router_llm_provider": "anthropic",
                    "router_llm_model": LLMModel.CLAUDE_3_HAIKU.value,
                }
            )

        renderer = TemplateRenderer()
        ctx = renderer._build_context(config)
        rendered = _render_router(renderer, ctx)

        expected = f'ChatAnthropic(model_name="{LLMModel.CLAUDE_3_HAIKU.value}", temperature=0)'
        assert expected in rendered
