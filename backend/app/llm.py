"""One structured Claude call: send a prompt, get a validated Pydantic object back.

Two ways to reach Claude, chosen with LLM_BACKEND in backend/.env:
- "api" (the default): the Anthropic API, billed to ANTHROPIC_API_KEY.
- "claude-code": your Claude subscription, through the Claude Agent SDK, which runs Claude Code headless with the
  login you made with `claude` (/login). Needs `uv sync --extra claude-code`. Claude Code prefers an API key to your
  login whenever one is in its environment, so in this mode the key is taken out of this process's environment.
  Anthropic doesn't allow offering claude.ai login in products you distribute; this is for running the app yourself.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()
log = logging.getLogger(__name__)
BACKEND = os.environ.get("LLM_BACKEND", "api")
if BACKEND == "claude-code":
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        os.environ.pop(var, None)
client = anthropic.Anthropic()
T = TypeVar("T", bound=BaseModel)


def ready() -> str | None:
    """Why Claude can't be called with the current settings, or None if it can."""
    if BACKEND == "claude-code":
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return "LLM_BACKEND=claude-code needs the Claude Agent SDK: run `uv sync --extra claude-code` in backend/."
        return None
    if BACKEND != "api":
        return f"Unknown LLM_BACKEND {BACKEND!r} in backend/.env: use api or claude-code."
    if not (client.api_key or client.auth_token):
        return "Add ANTHROPIC_API_KEY to backend/.env, or set LLM_BACKEND=claude-code to use your Claude subscription."
    return None


def ask(schema: type[T], system: str, prompt: str, model: str, effort: str) -> T:
    if BACKEND == "claude-code":
        # Callers are sync FastAPI endpoints running in worker threads, which have no event loop of their own.
        return asyncio.run(ask_claude_code(schema, system, prompt, model, effort))
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,  # thinking counts too, so leave room
        system=system,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        # Parsed below rather than via output_format, which raises mid-stream before stop_reason is known.
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude refused: {response.stop_details}")
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped early (stop_reason={response.stop_reason}, {response.usage.output_tokens} output tokens)")
    return schema.model_validate_json(answer_text(response.content))


def answer_text(content: list) -> str:
    """The answer's text. If a safety classifier declines partway (biology papers trip it), the response keeps the
    declined partial text, then a `fallback` block, then the fallback model's answer, which starts over. Only the
    text after the last fallback block is the answer."""
    fallbacks = [i for i, b in enumerate(content) if b.type == "fallback"]
    if fallbacks:
        log.info("safety fallback: %s answered instead of %s", content[fallbacks[-1]].to.model, content[fallbacks[0]].from_.model)
    answer = content[fallbacks[-1] + 1 :] if fallbacks else content
    return "".join(b.text for b in answer if b.type == "text")


# An empty working directory, so Claude Code finds no project files, CLAUDE.md or settings to pick up.
CLAUDE_CODE_CWD = Path(tempfile.gettempdir()) / "human-pretraining-claude-code"


async def ask_claude_code(schema: type[T], system: str, prompt: str, model: str, effort: str) -> T:
    """The same call through Claude Code on your subscription, set up to behave like the API call: only our system
    prompt, no tools, skills, MCP servers, settings or memory, and the same JSON schema enforced."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    CLAUDE_CODE_CWD.mkdir(exist_ok=True)
    options = ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        effort=effort,
        output_format={"type": "json_schema", "schema": anthropic.transform_schema(schema)},
        tools=[],
        skills=[],
        permission_mode="dontAsk",  # anything that would ask for permission is refused
        setting_sources=[],
        strict_mcp_config=True,
        cwd=CLAUDE_CODE_CWD,
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"},
    )
    result = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result = message
    except Exception as e:
        # query() yields an error result and then raises; report the result, which says what went wrong.
        if result is None or not result.is_error:
            raise
        log.debug("Claude Code raised after its error result: %r", e)
    if result is None or result.is_error or result.structured_output is None:
        detail = (result.errors or result.result or result.subtype) if result else "no result"
        raise RuntimeError(f"Claude Code didn't answer: {detail}")
    return schema.model_validate(result.structured_output)
