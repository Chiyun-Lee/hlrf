"""LLM interface: protocol, Anthropic backend, deterministic mock, disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000

HEADER_RE = re.compile(r"^([A-Z_]+): ?(.*)$", re.M)
# Leading whitespace allowed: render_card_for_prompt indents QUOTE lines by two spaces.
QUOTE_RE = re.compile(r"^[ \t]*QUOTE\[([^|\]]+)\|([^\]]+)\]: (.+)$", re.M)


class LLM(Protocol):
    """One method every backend implements."""

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        """Return a dict that satisfies `schema`."""
        ...


class LLMError(RuntimeError):
    """Raised when a backend cannot produce schema-valid output."""


# ---------------------------------------------------------------- schema check


def check_schema(data: object, schema: dict) -> list[str]:
    """Return the problems of `data` against the keyword subset we use ([] = valid)."""
    problems: list[str] = []
    _walk(data, schema, "$", problems)
    return problems


_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_ok(data: object, t: str) -> bool:
    """Check one JSON type name, with bool excluded from integer/number."""
    if t in ("integer", "number") and isinstance(data, bool):
        return False
    return isinstance(data, _TYPES.get(t, ()))


def _walk(data: object, schema: dict, path: str, problems: list[str]) -> None:
    """Recursive schema walk collecting problems."""
    if "anyOf" in schema:
        if not any(not _probe(data, sub) for sub in schema["anyOf"]):
            problems.append(f"{path}: matches no anyOf branch")
        return
    if "enum" in schema and data not in schema["enum"]:
        problems.append(f"{path}: {data!r} not in enum {schema['enum']}")
        return
    t = schema.get("type")
    if t is not None and not _type_ok(data, t):
        problems.append(f"{path}: expected {t}, got {type(data).__name__}")
        return
    if t == "object" and isinstance(data, dict):
        props: dict[str, dict] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in data:
                problems.append(f"{path}.{key}: missing required key")
        if schema.get("additionalProperties") is False:
            for key in data:
                if key not in props:
                    problems.append(f"{path}.{key}: unexpected key")
        for key, sub in props.items():
            if key in data:
                _walk(data[key], sub, f"{path}.{key}", problems)
    elif t == "array" and isinstance(data, list) and "items" in schema:
        for i, item in enumerate(data):
            _walk(item, schema["items"], f"{path}[{i}]", problems)


def _probe(data: object, schema: dict) -> list[str]:
    """Walk without touching the caller's problem list."""
    local: list[str] = []
    _walk(data, schema, "$", local)
    return local


# ------------------------------------------------------------------ anthropic


def resolve_model(role: Literal["main", "judge"] = "main") -> str:
    """Model id for a role, honouring JC_MODEL / JC_JUDGE_MODEL."""
    if role == "judge":
        return os.environ.get("JC_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    return os.environ.get("JC_MODEL", DEFAULT_MODEL)


class AnthropicLLM:
    """Structured JSON through the official Anthropic SDK."""

    def __init__(self, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        """Create the zero-arg client unless one is injected (tests)."""
        self.model = model
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        """One messages.create call with a JSON-schema output format; SDK failures surface as LLMError."""
        import anthropic

        t0 = time.monotonic()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AnthropicError as exc:
            raise LLMError(f"{kind}: {type(exc).__name__}: {exc}") from exc
        elapsed = time.monotonic() - t0
        usage = getattr(resp, "usage", None)
        log.info(
            "llm kind=%s model=%s in=%s out=%s elapsed=%.1fs",
            kind,
            self.model,
            getattr(usage, "input_tokens", "?"),
            getattr(usage, "output_tokens", "?"),
            elapsed,
        )
        stop = getattr(resp, "stop_reason", None)
        if stop in ("refusal", "max_tokens"):
            raise LLMError(f"{kind}: stop_reason={stop}")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise LLMError(f"{kind}: no text block in response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{kind}: invalid JSON: {exc}") from exc
        problems = check_schema(data, schema)
        if problems:
            raise LLMError(f"{kind}: output violates schema: {problems[:5]}")
        return data


# ------------------------------------------------------------ claude agent sdk


class ClaudeAgentLLM:
    """Structured JSON through the Claude Agent SDK, which runs on the Claude Code login (a subscription), not an API key.

    Every call is a fresh, tool-less, settings-free session in a scratch cwd, so no
    project CLAUDE.md or tool can leak into a prompt. Async under the hood; each
    call runs its own event loop, so it is safe from worker threads.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        cwd: str | Path | None = None,
        max_budget_usd: float = 2.0,
        timeout_s: float = 600.0,
    ) -> None:
        """Refuse to start if an API key is set: in non-interactive mode the key wins and is billed."""
        if os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ClaudeAgentLLM: unset ANTHROPIC_API_KEY so the Claude Code login is used")
        self.model = model
        self.cwd = Path(cwd) if cwd else Path(tempfile.mkdtemp(prefix="jc-agent-"))
        self.max_budget_usd = max_budget_usd
        self.timeout_s = timeout_s

    def _options(self, system: str, schema: dict) -> Any:
        """One isolated session: no tools, no settings, no prompts, JSON-schema output."""
        from claude_agent_sdk import ClaudeAgentOptions

        return ClaudeAgentOptions(
            system_prompt=system,
            model=self.model,
            max_turns=2,
            tools=[],
            allowed_tools=[],
            setting_sources=[],
            cwd=str(self.cwd),
            permission_mode="dontAsk",
            max_budget_usd=self.max_budget_usd,
            output_format={"type": "json_schema", "schema": schema},
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        )

    async def _run(self, kind: str, system: str, user: str, schema: dict) -> Any:
        """Drive query() to its ResultMessage."""
        from claude_agent_sdk import ResultMessage, query

        final = None
        async for msg in query(prompt=user, options=self._options(system, schema)):
            if isinstance(msg, ResultMessage):
                final = msg
        if final is None:
            raise LLMError(f"{kind}: no ResultMessage from the agent SDK")
        return final

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        """One agent session; SDK failures, refusals and schema misses surface as LLMError."""
        import asyncio

        t0 = time.monotonic()
        try:
            result = asyncio.run(asyncio.wait_for(self._run(kind, system, user, schema), timeout=self.timeout_s))
        except LLMError:
            raise
        except Exception as exc:  # CLINotFoundError, ProcessError, ResultError, TimeoutError, ...
            raise LLMError(f"{kind}: {type(exc).__name__}: {exc}") from exc
        log.info(
            "llm kind=%s model=%s backend=agent turns=%s cost_usd=%s elapsed=%.1fs",
            kind,
            self.model,
            getattr(result, "num_turns", "?"),
            getattr(result, "total_cost_usd", "?"),
            time.monotonic() - t0,
        )
        subtype = getattr(result, "subtype", "success")
        if getattr(result, "is_error", False) or subtype != "success":
            raise LLMError(f"{kind}: agent SDK returned {subtype}: {getattr(result, 'errors', None)}")
        data = getattr(result, "structured_output", None)
        if data is None:
            text = getattr(result, "result", None) or ""
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMError(f"{kind}: no structured_output and result is not JSON: {exc}") from exc
        problems = check_schema(data, schema)
        if problems:
            raise LLMError(f"{kind}: output violates schema: {problems[:5]}")
        return data


# ----------------------------------------------------------------------- mock


def _seed(kind: str, user: str) -> int:
    """Deterministic seed from (kind, user)."""
    return int(hashlib.sha256(f"{kind}\x00{user}".encode()).hexdigest()[:16], 16)


def parse_headers(user: str) -> dict[str, str]:
    """Header lines `NAME: value`; first occurrence wins."""
    out: dict[str, str] = {}
    for m in HEADER_RE.finditer(user):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def parse_quotes(user: str) -> list[dict[str, str]]:
    """Every QUOTE[id|loc]: text line as a Quote-shaped dict, in document order."""
    return [
        {"paper_id": m.group(1), "loc": m.group(2), "text": m.group(3).strip()}
        for m in QUOTE_RE.finditer(user)
    ]


def _fabricated(pid: str) -> dict[str, str]:
    """A quote that fails verification by design."""
    return {"paper_id": pid, "text": "no quote available", "loc": "none"}


def _first_words(text: str, n: int) -> str:
    """First n whitespace-separated words."""
    return " ".join(text.split()[:n])


def _sentences(text: str, min_len: int = 40) -> list[str]:
    """Sentences of >= min_len chars, verbatim, in order."""
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [p.strip() for p in parts if len(p.strip()) >= min_len]


class MockLLM:
    """Deterministic backend: derives outputs from the prompt headers and QUOTE lines."""

    def __init__(self, scripted: dict[str, Callable[[str], dict]] | None = None) -> None:
        """Optional `scripted[kind] = fn(user) -> dict` overrides."""
        self.scripted: dict[str, Callable[[str], dict]] = dict(scripted or {})
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        """Record the call, produce the result, self-validate."""
        with self._lock:
            self.calls.append((kind, user))
        fn = self.scripted.get(kind)
        result = fn(user) if fn is not None else self.default(kind, user, schema)
        problems = check_schema(result, schema)
        if problems:
            raise LLMError(f"mock output violates schema: {problems[:5]}")
        return result

    def default(self, kind: str, user: str, schema: dict) -> dict:
        """The deterministic rule for each kind (§3.1 of DESIGN.md)."""
        rng = random.Random(_seed(kind, user))
        headers = parse_headers(user)
        quotes = parse_quotes(user)
        handler = getattr(self, f"_kind_{kind}", None)
        if handler is not None:
            return handler(rng, headers, quotes, user)
        return self._generic(rng, schema, quotes, "root")

    # -- per-kind rules -------------------------------------------------------

    @staticmethod
    def _quotes_for(quotes: list[dict[str, str]], pid: str) -> list[dict[str, str]]:
        """QUOTE lines of one paper."""
        return [q for q in quotes if q["paper_id"] == pid]

    def _first_quote(self, quotes: list[dict[str, str]], pid: str) -> dict[str, str]:
        """First QUOTE line of a paper, or a fabricated one."""
        mine = self._quotes_for(quotes, pid)
        return dict(mine[0]) if mine else _fabricated(pid)

    def _kind_ingest(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Card fields read off the PDF text."""
        pid = h.get("PAPER_ID", "paper")
        body = user.split("TEXT:", 1)[1] if "TEXT:" in user else user
        body = body.replace("<<<PDF_TEXT_BEGIN>>>", "").replace("<<<PDF_TEXT_END>>>", "")
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        title = lines[0] if lines else pid
        hint = h.get("YEAR_HINT", "")
        year = int(hint) if re.fullmatch(r"\d{4}", hint) else 2020
        sents = _sentences(body)

        def item(sentence: str) -> dict:
            return {
                "text": "Claims: " + _first_words(sentence, 8),
                "quote": {"paper_id": pid, "text": sentence, "loc": "p1"},
            }

        return {
            "citekey": pid,
            "title": title,
            "year": year,
            "date": f"{year}-01-01",
            "authors": ["Mock Author"],
            "abstract": body.strip()[:300],
            "claims": [item(s) for s in sents[:2]],
            "methods": ["mock method"],
            "data": ["mock data"],
            "limits": [item(s) for s in sents[2:3]],
        }

    def _kind_map(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Pair relation with the first quote of each side."""
        a, b = _split_pair(h.get("PAIR", ""))
        relation = rng.choices(
            ["agree", "disagree", "shared_limitation", "unrelated"], weights=[3, 3, 3, 1]
        )[0]
        return {
            "relation": relation,
            "quote_a": self._first_quote(q, a),
            "quote_b": self._first_quote(q, b),
            "note": f"mock: {a} vs {b} ({relation})",
        }

    def _kind_debate_turn(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """The speaker restates the claim with its own first quote."""
        s = h.get("SPEAKER", "")
        mine = self._quotes_for(q, s)
        return {
            "text": f"{s} maintains: {h.get('CLAIM', '')}",
            "quotes": [dict(mine[0])] if mine else [],
        }

    def _kind_debate_verdict(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Random legal verdict."""
        return {"verdict": rng.choice(["stands", "contested", "unresolved"]), "reason": "mock verdict"}

    def _kind_directions(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """N directions, each resting on two papers' first quotes."""
        n = int(h.get("N", "0") or 0)
        ids = list(dict.fromkeys(x["paper_id"] for x in q))
        out = []
        for i in range(n):
            if not ids:
                break
            pair = rng.sample(ids, 2) if len(ids) >= 2 else [ids[0], ids[0]]
            q1, q2 = self._first_quote(q, pair[0]), self._first_quote(q, pair[1])
            from_a, to_b = _first_words(q1["text"], 6), _first_words(q2["text"], 6)
            out.append(
                {
                    "text": f"The field moves from {from_a} to {to_b} (#{i})",
                    "from_a": from_a,
                    "to_b": to_b,
                    "because": f"{pair[0]} and {pair[1]} both point there",
                    "papers": sorted(pair),
                    "quotes": [q1, q2],
                    "confidence": round(0.3 + rng.randrange(60) / 100, 2),
                }
            )
        return {"directions": out}

    _kind_baseline = _kind_directions

    def _kind_judge(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Random verdict naming one after-T paper unless miss."""
        after_ids = [x.strip() for x in h.get("AFTER_IDS", "").split(",") if x.strip()]
        verdict = rng.choice(["hit", "partial", "miss"])
        pid = rng.choice(after_ids) if verdict != "miss" and after_ids else None
        return {"verdict": verdict, "after_paper_id": pid, "reason": f"mock judge: {verdict}"}

    def _kind_hypotheses(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Up to N hypotheses, each on two papers' first quotes, sources in turn."""
        ids = list(dict.fromkeys(x["paper_id"] for x in q))
        out = []
        for i in range(min(int(h.get("N", "0") or 0), len(ids))):
            pair = sorted(rng.sample(ids, 2)) if len(ids) >= 2 else [ids[0]]
            out.append(
                {
                    "text": f"Mock hypothesis {i + 1}: {' and '.join(pair)} together predict an untested effect",
                    "mechanism": f"mock mechanism {i + 1}",
                    "test": f"mock test {i + 1}",
                    "prediction": f"mock prediction {i + 1}",
                    "source": ("combine", "resolve", "gap", "extend")[i % 4],
                    "papers": pair,
                    "quotes": [self._first_quote(q, p) for p in pair],
                }
            )
        return {"hypotheses": out}

    def _kind_critique(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """The speaker supports or objects with its own first quote."""
        s = h.get("SPEAKER", "")
        mine = self._quotes_for(q, s)
        stance = rng.choice(["supports", "objects"])
        return {"stance": stance, "text": f"{s} {stance}", "quotes": [dict(mine[0])] if mine else []}

    def _kind_revise(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Keep, revise (prefixing the text) or drop, the fields read back from the headers."""
        decision = rng.choices(["keep", "revise", "drop"], weights=[2, 2, 1])[0]
        fields = {k.lower(): h.get(k, "") for k in ("HYPOTHESIS", "MECHANISM", "TEST", "PREDICTION")}
        text = fields.pop("hypothesis")
        return {"decision": decision, "text": f"Revised: {text}" if decision == "revise" else text, **fields, "reason": f"mock {decision}"}

    def _kind_compare(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Random winner."""
        return {"winner": rng.choice(["A", "B"]), "reason": "mock comparison"}

    # -- generic fallback -----------------------------------------------------

    def _kind_synthesis(self, rng: random.Random, h: dict[str, str], q: list, user: str) -> dict:
        """Overview prose plus one key point per kind, each backed by a real QUOTE line from a distinct paper."""
        by_paper: dict[str, dict[str, str]] = {}
        for quote in q:
            by_paper.setdefault(quote["paper_id"], quote)
        pool = [dict(v) for v in by_paper.values()]
        points = []
        for i, kind in enumerate(("consensus", "dissent", "gap", "direction")):
            if i < len(pool):
                points.append({"kind": kind, "text": f"Mock {kind} point {i + 1} on {pool[i]['paper_id']}.", "quotes": [pool[i]]})
        overview = f"Mock overview of {len(by_paper)} papers for agenda: {h.get('AGENDA', '')}. " * 3
        return {"overview": overview.strip(), "key_points": points}

    def _generic(self, rng: random.Random, schema: dict, quotes: list, field: str) -> Any:
        """Schema walk producing one plausible value."""
        if "anyOf" in schema:
            if any(s.get("type") == "null" for s in schema["anyOf"]):
                return None
            return self._generic(rng, schema["anyOf"][0], quotes, field)
        if "enum" in schema:
            return rng.choice(schema["enum"])
        t = schema.get("type")
        if t == "object":
            props: dict[str, dict] = schema.get("properties", {})
            if set(props) == {"paper_id", "text", "loc"}:
                return dict(quotes[0]) if quotes else _fabricated("none")
            return {k: self._generic(rng, sub, quotes, k) for k, sub in props.items()}
        if t == "array":
            return [self._generic(rng, schema.get("items", {}), quotes, field)]
        if t == "string":
            return f"{field} {rng.getrandbits(32):08x}"
        if t == "integer":
            return 1
        if t == "number":
            return 0.5
        if t == "boolean":
            return True
        return None


def _split_pair(value: str) -> tuple[str, str]:
    """Parse `a | b`."""
    parts = [p.strip() for p in value.split("|")]
    if len(parts) != 2:
        return value.strip(), value.strip()
    return parts[0], parts[1]


# ---------------------------------------------------------------------- cache


def cache_key(kind: str, system: str, user: str, schema: dict, model: str | None = None) -> str:
    """sha256 of the canonical JSON of the call arguments; the model joins the key when known."""
    payload: dict[str, Any] = {"kind": kind, "system": system, "user": user, "schema": schema}
    if model is not None:
        payload["model"] = model
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


class CachedLLM:
    """Disk cache in front of any LLM; writes only schema-valid results; keyed by the inner model too."""

    def __init__(self, inner: LLM, dir: str | Path = ".jc_cache") -> None:
        """Create the cache directory lazily on first write."""
        self.inner = inner
        self.dir = Path(dir)
        self._lock = threading.Lock()

    @property
    def model(self) -> str | None:
        """The inner backend's model id, if it has one (so a model change never serves stale answers)."""
        model = getattr(self.inner, "model", None)
        return str(model) if model is not None else None

    def _path(self, key: str) -> Path:
        """File for one key."""
        return self.dir / f"{key}.json"

    def _key(self, kind: str, system: str, user: str, schema: dict) -> str:
        """Cache key of one call under the inner model."""
        return cache_key(kind, system, user, schema, self.model)

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        """Hit: parsed file. Miss: call inner and persist if valid."""
        key = self._key(kind, system, user, schema)
        path = self._path(key)
        with self._lock:
            if path.exists():
                log.info("cache hit kind=%s key=%s", kind, key[:12])
                return json.loads(path.read_text())
        result = self.inner.complete_json(kind, system, user, schema)
        problems = check_schema(result, schema)
        if problems:
            raise LLMError(f"{kind}: output violates schema, not cached: {problems[:5]}")
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(result, ensure_ascii=False))
            os.replace(tmp, path)
        return result

    def drop(self, kind: str, system: str, user: str, schema: dict) -> bool:
        """Delete one entry; True if it existed."""
        path = self._path(self._key(kind, system, user, schema))
        with self._lock:
            if path.exists():
                path.unlink()
                return True
            return False


# -------------------------------------------------------------------- factory


def default_backend() -> str:
    """The app's LLM_BACKEND (backend/.env: `claude-code` -> agent, `api` -> anthropic) when set; otherwise `anthropic`
    when an API key is set, else `agent` (the Claude Code login)."""
    app_backend = os.environ.get("LLM_BACKEND")
    if app_backend == "claude-code":
        return "agent"
    if app_backend == "api" and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "agent"


def get_llm(role: Literal["main", "judge"] = "main") -> LLM:
    """Backend selected by JC_LLM (mock | agent | anthropic), cached unless JC_CACHE=0 (in JC_CACHE_DIR, default .jc_cache)."""
    backend = os.environ.get("JC_LLM") or default_backend()
    if backend == "mock":
        return MockLLM()
    if backend == "anthropic":
        llm: LLM = AnthropicLLM(resolve_model(role))
    elif backend == "agent":
        llm = ClaudeAgentLLM(resolve_model(role))
    else:
        raise ValueError(f"JC_LLM must be 'mock', 'agent' or 'anthropic', got {backend!r}")
    if os.environ.get("JC_CACHE", "1") != "0":
        llm = CachedLLM(llm, os.environ.get("JC_CACHE_DIR", ".jc_cache"))
    return llm
