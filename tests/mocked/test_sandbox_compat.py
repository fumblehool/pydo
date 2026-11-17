# pylint: disable=missing-docstring
"""Mocked tests for Sandbox.compat e2b and modal factories."""
import json

import pytest
import responses

from pydo.sandbox import Sandbox as NativeSandbox
from pydo.sandbox.compat.e2b import Commands
from pydo.sandbox.compat.e2b import Sandbox as E2BSandbox
from pydo.sandbox.compat.modal import Sandbox as ModalSandbox
from pydo.sandbox.errors import CommandExitError, SandboxError

BASE = "https://sandbox.test"


@pytest.fixture
def token_env(monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "test-token")
    monkeypatch.setenv("DIGITALOCEAN_API_URL", BASE)
    monkeypatch.delenv("DIGITALOCEAN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DIGITALOCEAN_REGION", raising=False)


def test_unknown_api_raises():
    with pytest.raises(SandboxError, match="unknown sandbox api"):
        NativeSandbox.compat("fly")


def test_e2b_rejects_template_lifetime_and_user():
    with pytest.raises(SandboxError, match="template"):
        E2BSandbox.create(template="gpu")
    with pytest.raises(SandboxError, match="lifetime"):
        E2BSandbox.create(template="base", timeout=300)
    with pytest.raises(SandboxError, match="user"):
        Commands(None).run("echo hi", user="root")


def test_modal_rejects_image_and_entrypoint():
    with pytest.raises(SandboxError, match="exec"):
        ModalSandbox.create("echo", "hi")
    with pytest.raises(SandboxError, match="image"):
        ModalSandbox.create(image="debian")
    with pytest.raises(SandboxError, match="lifetime"):
        ModalSandbox.create(timeout=60)


@responses.activate
def test_e2b_create_run_and_kill(token_env):
    def created(request):
        body = request.body if isinstance(request.body, str) else request.body.decode()
        assert "adapter: sandbox" in body
        assert "name: pydo" in body
        payload = {"session": {"session_id": "sess-e2b"}}
        return (201, {"Content-Type": "application/json"}, json.dumps(payload))

    responses.add_callback(
        responses.POST, BASE + "/v2/agents/sessions", callback=created
    )
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions/sess-e2b/sandbox/exec",
        json={"exit_code": 0, "stdout": "hi\n", "stderr": ""},
        status=200,
    )
    responses.add(responses.DELETE, BASE + "/v2/agents/sessions/sess-e2b", status=204)

    sb = NativeSandbox.compat("E2B").create(template="base", name="pydo")
    assert isinstance(sb, E2BSandbox)
    assert sb.sandbox_id == "sess-e2b"
    assert sb.commands.run("echo hi").stdout == "hi\n"
    sent = json.loads(responses.calls[1].request.body)
    assert sent["argv"] == ["sh", "-c", "echo hi"]
    assert sb.kill() is True


@responses.activate
def test_e2b_nonzero_raises(token_env):
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions",
        json={"session": {"session_id": "sess-e2b"}},
        status=201,
    )
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions/sess-e2b/sandbox/exec",
        json={"exit_code": 2, "stdout": "partial", "stderr": "nope"},
        status=200,
    )
    sb = E2BSandbox.create()
    with pytest.raises(CommandExitError) as caught:
        sb.commands.run("false")
    assert caught.value.exit_code == 2
    assert caught.value.stdout == "partial"


@responses.activate
def test_modal_exec_terminate_and_nonzero(token_env):
    def created(request):
        body = request.body if isinstance(request.body, str) else request.body.decode()
        assert "name: pydo" in body
        payload = {"session": {"session_id": "sess-modal"}}
        return (201, {"Content-Type": "application/json"}, json.dumps(payload))

    responses.add_callback(
        responses.POST, BASE + "/v2/agents/sessions", callback=created
    )
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions/sess-modal/sandbox/exec",
        json={"exit_code": 0, "stdout": "hi\n", "stderr": ""},
        status=200,
    )
    responses.add(
        responses.POST,
        BASE + "/v2/agents/sessions/sess-modal/sandbox/exec",
        json={"exit_code": 2, "stdout": "partial", "stderr": "nope"},
        status=200,
    )
    responses.add(responses.DELETE, BASE + "/v2/agents/sessions/sess-modal", status=204)

    sb = NativeSandbox.compat("modal").create(name="pydo")
    assert isinstance(sb, ModalSandbox)
    proc = sb.exec("echo", "hi", workdir="/tmp", text=True)
    assert proc.stdout.read() == "hi\n"
    assert proc.wait() == 0
    sent = json.loads(responses.calls[1].request.body)
    assert sent["argv"] == ["echo", "hi"]
    assert sent["workdir"] == "/tmp"
    failed = sb.exec("false", text=False)
    assert failed.returncode == 2
    assert failed.stdout.read() == b"partial"
    assert sb.terminate() is True


def test_modal_exec_rejects_env_without_a_sandbox():
    sb = ModalSandbox.__new__(ModalSandbox)
    with pytest.raises(SandboxError, match="env"):
        sb.exec("echo", "hi", env={"A": "b"})
    with pytest.raises(SandboxError, match="requires a command"):
        sb.exec()
