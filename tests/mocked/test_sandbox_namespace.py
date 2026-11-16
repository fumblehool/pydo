# pylint: disable=missing-docstring
"""Mocked tests for ``pydo.sandbox``, the hand-written sandbox client."""
import json

import pytest
import responses

from pydo.sandbox import (
    AuthenticationError,
    Client,
    CommandExitError,
    Sandbox,
    SandboxError,
)

BASE = "https://sandbox.test"


@pytest.fixture
def token_env(monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "test-token")
    monkeypatch.setenv("DIGITALOCEAN_API_URL", BASE)
    monkeypatch.delenv("DIGITALOCEAN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DIGITALOCEAN_REGION", raising=False)


@responses.activate
def test_create_and_run_match_the_readme(token_env):
    def created(request):
        assert request.headers["Content-Type"].startswith("application/x-yaml")
        body = request.body if isinstance(request.body, str) else request.body.decode()
        assert "adapter: sandbox" in body
        assert "sizeSlug: s-1vcpu-1gb" in body
        payload = {"session": {"session_id": "sess-1"}}
        return (201, {"Content-Type": "application/json"}, json.dumps(payload))

    responses.add_callback(
        responses.POST, BASE + "/v2/agents/sessions", callback=created
    )
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions/sess-1/sandbox/exec",
        json={"exit_code": 0, "stdout": "Hello from DigitalOcean!\n", "stderr": ""},
        status=200,
    )
    responses.add(responses.DELETE, BASE + "/v2/agents/sessions/sess-1", status=204)

    sandbox = Sandbox.create(size="s-1vcpu-1gb")
    result = sandbox.commands.run('echo "Hello from DigitalOcean!"', cwd="/workspace")
    assert sandbox.sandbox_id == "sess-1"
    assert result.stdout == "Hello from DigitalOcean!\n"
    sent = json.loads(responses.calls[1].request.body)
    assert sent["argv"] == ["sh", "-c", 'echo "Hello from DigitalOcean!"']
    assert sent["workdir"] == "/workspace"
    assert sandbox.kill() is True


@responses.activate
def test_client_token_and_per_call_override():
    seen = []

    def created(request):
        seen.append(request.headers["Authorization"])
        payload = {"session": {"session_id": "from-client"}}
        return (201, {"Content-Type": "application/json"}, json.dumps(payload))

    responses.add_callback(
        responses.POST, BASE + "/v2/agents/sessions", callback=created
    )
    client = Client(token="client-token", api_url=BASE)
    sandbox = client.sandbox.create(token="call-token")
    assert sandbox.sandbox_id == "from-client"
    assert seen == ["Bearer call-token"]
    assert dir(client) == ["sandbox"]


@responses.activate
def test_nonzero_exit_and_envs_refused(token_env):
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions",
        json={"session": {"session_id": "sess-1"}},
        status=201,
    )
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions/sess-1/sandbox/exec",
        json={"exit_code": 2, "stdout": "partial", "stderr": "nope"},
        status=200,
    )
    sandbox = Sandbox.create(manifest="kind: Agent\n")
    with pytest.raises(CommandExitError) as caught:
        sandbox.commands.run("false")
    assert caught.value.exit_code == 2
    assert caught.value.stdout == "partial"
    with pytest.raises(SandboxError):
        sandbox.commands.run("echo hi", envs={"A": "b"})


def test_requires_a_token(monkeypatch):
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    monkeypatch.delenv("DIGITALOCEAN_ACCESS_TOKEN", raising=False)
    with pytest.raises(AuthenticationError):
        Sandbox.create()


@pytest.mark.asyncio
async def test_async_client_create_and_run(token_env):
    from aioresponses import aioresponses

    from pydo.sandbox.aio import Client as AsyncClient

    with aioresponses() as mocked:
        mocked.post(
            BASE + "/v2/agents/sessions",
            payload={"session": {"session_id": "sess-async"}},
            status=201,
        )
        mocked.post(
            BASE + "/v2/agents/sessions/sess-async/sandbox/exec",
            payload={"exit_code": 0, "stdout": "async\n", "stderr": ""},
            status=200,
        )
        client = AsyncClient(api_key="async-token", api_url=BASE)
        sandbox = await client.sandbox.create(name="demo")
        result = await sandbox.commands.run("echo async")
    assert sandbox.sandbox_id == "sess-async"
    assert result.stdout == "async\n"
