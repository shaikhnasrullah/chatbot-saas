"""Thin wrapper around the Anthropic API. Tests monkeypatch `complete`."""
from . import config


class LLMUnavailable(RuntimeError):
    pass


_client = None


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def complete(system: str, user: str, max_tokens: int = 4000) -> str:
    global _client
    if not config.ANTHROPIC_API_KEY:
        raise LLMUnavailable("ANTHROPIC_API_KEY set nahi hai (.env file mein daalo).")
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
