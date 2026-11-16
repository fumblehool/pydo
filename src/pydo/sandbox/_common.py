# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""Shared helpers for the sync and async sandbox clients."""
from __future__ import annotations

import os
from typing import Mapping, Optional, Sequence, Union

from pydo.sandbox.errors import AuthenticationError, SandboxError

DEFAULT_API_URL = "https://api.digitalocean.com"
USER_AGENT = "pydo-sandbox/0.44.0"
MAX_EXEC_SECONDS = 240

Command = Union[str, Sequence[str]]


def resolve_connection(
    token: Optional[str] = None,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    region: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
):
    """Token and API origin. ``api_key`` is an alias of ``token``.

    A per-call value wins over the environment, matching ``pydo.inference.Client``.
    """
    source = os.environ if env is None else env
    resolved = (
        token
        or api_key
        or source.get("DIGITALOCEAN_TOKEN")
        or source.get("DIGITALOCEAN_ACCESS_TOKEN")
    )
    if not resolved:
        raise AuthenticationError(
            "A token is required: pass token (or api_key), or set DIGITALOCEAN_TOKEN"
        )
    chosen_region = region or source.get("DIGITALOCEAN_REGION")
    origin = api_url or source.get("DIGITALOCEAN_API_URL")
    if not origin and chosen_region:
        origin = "https://api-{}.digitalocean.com".format(chosen_region)
    if not origin:
        origin = DEFAULT_API_URL
    return resolved, origin.rstrip("/")


def default_manifest(name: Optional[str], size: Optional[str]) -> str:
    """Minimal session manifest. ``adapter: sandbox`` is a machine with no agent."""
    sandbox_name = name or "sandbox-{}".format(os.urandom(4).hex())
    lines = [
        "apiVersion: agents.digitalocean.com/v1alpha1",
        "kind: Agent",
        "metadata:",
        "  name: {}".format(sandbox_name),
        "spec:",
        "  runtime:",
        "    adapter: sandbox",
    ]
    if size:
        lines.extend(["  sandbox:", "    sizeSlug: {}".format(size)])
    return "\n".join(lines) + "\n"


def to_argv(cmd: Command) -> list:
    """A string runs through ``sh -c``. A sequence is the argv."""
    if isinstance(cmd, str):
        if not cmd.strip():
            raise SandboxError("cmd is empty")
        return ["sh", "-c", cmd]
    argv = [str(part) for part in cmd]
    if not argv:
        raise SandboxError("cmd is empty")
    return argv


def session_id_from(payload) -> str:
    session = {}
    if isinstance(payload, dict):
        session = payload.get("session") or {}
    session_id = None
    if isinstance(session, dict):
        session_id = session.get("session_id") or session.get("id")
    if session_id is None and isinstance(payload, dict):
        session_id = payload.get("session_id")
    if not session_id:
        raise SandboxError("create session response did not include a session id")
    return str(session_id)


def exec_body(cmd: Command, cwd: Optional[str], timeout: Optional[float]):
    """JSON body for ``POST .../sandbox/exec``, plus the HTTP deadline in seconds."""
    body = {"argv": to_argv(cmd)}
    deadline = 60.0
    if cwd:
        body["workdir"] = cwd
    if timeout is not None:
        seconds = int(timeout) if timeout == int(timeout) else int(timeout) + 1
        if seconds > MAX_EXEC_SECONDS:
            raise SandboxError(
                "timeout is above the {}s exec cap".format(MAX_EXEC_SECONDS)
            )
        body["timeout_seconds"] = seconds
        deadline = float(timeout) + 5
    return body, deadline


def reject_unsupported(envs, background, stdin) -> None:
    if envs:
        raise SandboxError(
            "envs is not supported: the public exec body has no env field, "
            "so values would have to ride in argv"
        )
    if background:
        raise SandboxError("background commands are not on this API yet")
    if stdin:
        raise SandboxError("stdin is not supported on this exec endpoint yet")


def command_result(payload):
    data = payload or {}
    return (
        int(data.get("exit_code") or 0),
        data.get("stdout") or "",
        data.get("stderr") or "",
    )
