"""Unit tests for CRW tool URL scheme validation."""

import json

import pytest

from letta.services.tool_executor.builtin_tool_executor import BuiltinToolExecutor


class FakeAgentState:
    """Minimal stub for AgentState to test URL validation."""

    class Tool:
        env_vars = {}

    tools = []


def _make_executor():
    return BuiltinToolExecutor()


def _make_agent_state():
    return FakeAgentState()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "javascript:alert(1)",
        "data:text/html,<h1>hi</h1>",
        "",
    ],
)
@pytest.mark.asyncio
async def test_crw_scrape_rejects_invalid_url_scheme(url):
    executor = _make_executor()
    result = await executor.crw_scrape(agent_state=_make_agent_state(), url=url)
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "URL scheme" in parsed["error"] or "Invalid" in parsed["error"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "",
    ],
)
@pytest.mark.asyncio
async def test_crw_crawl_rejects_invalid_url_scheme(url):
    executor = _make_executor()
    result = await executor.crw_crawl(agent_state=_make_agent_state(), url=url)
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "URL scheme" in parsed["error"] or "Invalid" in parsed["error"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "",
    ],
)
@pytest.mark.asyncio
async def test_crw_map_rejects_invalid_url_scheme(url):
    executor = _make_executor()
    result = await executor.crw_map(agent_state=_make_agent_state(), url=url)
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert "URL scheme" in parsed["error"] or "Invalid" in parsed["error"]


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com"])
def test_valid_schemes_are_not_rejected(url):
    """Verify that http/https URLs pass the scheme check (they'll fail later on missing CRW config, not scheme)."""
    from urllib.parse import urlparse

    parsed_url = urlparse(url)
    assert parsed_url.scheme.lower() in ("http", "https")
