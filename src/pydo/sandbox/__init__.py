# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""Sandbox entry point: ``from pydo.sandbox import Client``.

Same idea as :class:`pydo.inference.Client`: a small client you construct with
``token`` or ``api_key``, instead of the generated operation classes. The calls
match the dots ``Sandbox`` (create, run a command, pause, resume, kill).

The generated client can only send the JSON ``{name, config_id}`` create form.
Creating a sandbox sends the session manifest as YAML, so this package calls
the API directly, the way the dots sandbox skips Kiota.

Example::

    import os
    from pydo.sandbox import Client

    client = Client(token=os.environ["DIGITALOCEAN_TOKEN"])
    sandbox = client.sandbox.create(size="s-1vcpu-1gb")
    print(sandbox.commands.run('echo "Hello from DigitalOcean!"').stdout)
    sandbox.kill()
"""
from __future__ import annotations

from typing import Optional

import requests

from pydo.sandbox._common import (
    USER_AGENT,
    command_result,
    default_manifest,
    exec_body,
    reject_unsupported,
    resolve_connection,
    session_id_from,
)
from pydo.sandbox.errors import (
    AuthenticationError,
    CommandExitError,
    NotFoundError,
    SandboxError,
)

__all__ = [
    "AuthenticationError",
    "Client",
    "CommandExitError",
    "CommandResult",
    "Commands",
    "NotFoundError",
    "Sandbox",
    "SandboxError",
]


class CommandResult:
    """Output of a finished command."""

    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class Commands:
    """Commands inside one sandbox."""

    def __init__(self, http: "SandboxHttp", sandbox_id: str):
        self._http = http
        self._id = sandbox_id

    def run(
        self,
        cmd,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        envs=None,
        background: bool = False,
        stdin=None,
    ) -> CommandResult:
        """Run a command and wait. A string is ``sh -c``. A list is the argv.

        ``timeout`` is seconds. A non-zero exit raises :class:`CommandExitError`.
        """
        reject_unsupported(envs, background, stdin)
        body, deadline = exec_body(cmd, cwd, timeout)
        payload = self._http.request(
            "POST",
            "/v2/agents/sessions/{}/sandbox/exec".format(self._id),
            json_body=body,
            timeout=deadline,
        )
        exit_code, stdout, stderr = command_result(payload)
        if exit_code != 0:
            raise CommandExitError(exit_code, stdout, stderr)
        return CommandResult(exit_code, stdout, stderr)


class Sandbox:
    """One sandbox. Today this is a session at ``/v2/agents/sessions``."""

    def __init__(self, http: "SandboxHttp", sandbox_id: str):
        self.sandbox_id = sandbox_id
        self.commands = Commands(http, sandbox_id)
        self._http = http

    @classmethod
    def create(
        cls,
        *,
        size: Optional[str] = None,
        name: Optional[str] = None,
        manifest: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        region: Optional[str] = None,
        timeout: float = 120,
    ) -> "Sandbox":
        """Create a sandbox. Reads ``DIGITALOCEAN_TOKEN`` when no token is passed."""
        http = SandboxHttp(token, api_key, api_url, region, timeout)
        yaml = manifest if manifest is not None else default_manifest(name, size)
        payload = http.request(
            "POST",
            "/v2/agents/sessions",
            raw_body=yaml,
            content_type="application/x-yaml",
            timeout=timeout,
        )
        return cls(http, session_id_from(payload))

    @classmethod
    def compat(cls, api: str):
        """Return a factory whose methods match another sandbox SDK.

        The machine is still a DigitalOcean session. ``api`` is ``"e2b"`` or
        ``"modal"``.

        ::

            sb = Sandbox.compat("e2b").create(template="base")
            sb.commands.run("echo hi")
            sb.kill()

            sb = Sandbox.compat("modal").create(name="pydo")
            sb.exec("echo", "hi")
            sb.terminate()

        The same classes live at ``pydo.sandbox.compat.e2b.Sandbox`` and
        ``pydo.sandbox.compat.modal.Sandbox``. Arguments DigitalOcean cannot
        express raise :class:`SandboxError`.
        """
        from pydo.sandbox.compat import factory

        return factory(api)

    def kill(self) -> bool:
        """Delete the session."""
        self._http.request("DELETE", self._path())
        return True

    def pause(self) -> None:
        self._http.request("POST", self._path() + "/pause")

    def resume(self) -> None:
        self._http.request("POST", self._path() + "/resume")

    def _path(self) -> str:
        return "/v2/agents/sessions/{}".format(self.sandbox_id)


class _SandboxFactory:
    """``client.sandbox.create(...)``, with the client's credentials as defaults."""

    def __init__(self, client: "Client"):
        self._client = client

    def create(
        self,
        *,
        size: Optional[str] = None,
        name: Optional[str] = None,
        manifest: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        region: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Sandbox:
        """Create a sandbox. A token passed here overrides the client's token."""
        parent = self._client
        if token is not None or api_key is not None:
            use_token, use_key = token, api_key
        else:
            use_token, use_key = parent.token, parent.api_key
        if api_url is not None or region is not None:
            use_url, use_region = api_url, region
        else:
            use_url, use_region = parent.api_url, parent.region
        return Sandbox.create(
            size=size,
            name=name,
            manifest=manifest,
            token=use_token,
            api_key=use_key,
            api_url=use_url,
            region=use_region,
            timeout=parent.timeout if timeout is None else timeout,
        )


class Client:
    """Binds a token to ``client.sandbox``, like :class:`pydo.inference.Client`.

    :param token: DigitalOcean API token.
    :param api_key: Alias of ``token``.
    :param timeout: HTTP deadline in seconds. Default 120, as on the inference client.
    :param api_url: API origin. Overrides ``region``.
    :param region: Selects ``https://api-<region>.digitalocean.com``.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        timeout: float = 120,
        api_url: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        self.token = token
        self.api_key = api_key
        self.timeout = timeout
        self.api_url = api_url
        self.region = region
        self.sandbox = _SandboxFactory(self)

    def __dir__(self):
        return ["sandbox"]

    def __repr__(self) -> str:
        return "<pydo.sandbox.Client>"


class SandboxHttp:
    """Small ``requests`` client. Not the generated Autorest pipeline."""

    def __init__(self, token, api_key, api_url, region, timeout):
        resolved, origin = resolve_connection(token, api_key, api_url, region)
        self._token = resolved
        self._origin = origin
        self._timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        json_body=None,
        raw_body=None,
        content_type: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        headers = {
            "Authorization": "Bearer {}".format(self._token),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data = None
        json_payload = None
        if raw_body is not None:
            data = raw_body
            headers["Content-Type"] = content_type or "text/plain"
        elif json_body is not None:
            json_payload = json_body
        response = requests.request(
            method,
            self._origin + path,
            headers=headers,
            data=data,
            json=json_payload,
            timeout=self._timeout if timeout is None else timeout,
        )
        text = response.text
        if response.status_code >= 400:
            if response.status_code in (401, 403):
                raise AuthenticationError(
                    "authentication failed ({}): {}".format(response.status_code, text)
                )
            if response.status_code == 404:
                raise NotFoundError(text)
            raise SandboxError("HTTP {}: {}".format(response.status_code, text))
        if not text:
            return None
        content = response.headers.get("Content-Type", "")
        if "json" in content or text[:1] in ("{", "["):
            return response.json()
            return text
