"""One structured Claude call: send a prompt (or a conversation), get a validated Pydantic object back."""

import logging
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()
log = logging.getLogger(__name__)
client = anthropic.Anthropic()
T = TypeVar("T", bound=BaseModel)


def ask(schema: type[T], system: str, prompt: str | list, model: str, effort: str, tries: int = 2) -> T:
    """`prompt` is a user message (text, or content blocks such as images + text) or a full list of messages.

    An answer that is refused, cut short or doesn't fit `schema` is retried once (`tries`) before giving up: these are
    usually one-offs (a safety classifier misfiring on a biology paper, say)."""
    messages = prompt if isinstance(prompt, list) and prompt and "role" in prompt[0] else [{"role": "user", "content": prompt}]
    for attempt in range(1, tries + 1):
        try:
            return _ask_once(schema, system, messages, model, effort)
        except (RuntimeError, ValidationError) as e:
            if attempt == tries:
                raise
            log.warning("retrying %s after: %s", schema.__name__, str(e)[:200])


def _ask_once(schema: type[T], system: str, messages: list, model: str, effort: str) -> T:
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,  # thinking counts too, so leave room
        system=system,
        messages=messages,
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
