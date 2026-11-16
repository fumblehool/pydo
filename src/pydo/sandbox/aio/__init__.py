# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""Async sandbox entry point: ``from pydo.sandbox.aio import Client``.

Asynchronous twin of :class:`pydo.sandbox.Client`. Same surface, ``await``-friendly.
"""
from __future__ import annotations

import json
from typing import Optional

import aiohttp

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
from pydo.sandbox import CommandResult

__all__ = ["Client", "Sandbox"]


class Commands:
    def __init__(self, http: "SandboxHttp", sandbox_id: str):
        self._http = http
        self._id = sandbox_id

    async def run(
        self,
        cmd,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        envs=None,
        background: bool = False,
        stdin=None,
    ) -> CommandResult:
        reject_unsupported(envs, background, stdin)
        body, deadline = exec_body(cmd, cwd, timeout)
        payload = await self._http.request(
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
    def __init__(self, http: "SandboxHttp", sandbox_id: str):
        self.sandbox_id = sandbox_id
        self.commands = Commands(http, sandbox_id)
        self._http = http

    @classmethod
    async def create(
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
        http = SandboxHttp(token, api_key, api_url, region, timeout)
        yaml = manifest if manifest is not None else default_manifest(name, size)
        payload = await http.request(
            "POST",
            "/v2/agents/sessions",
            raw_body=yaml,
            content_type="application/x-yaml",
            timeout=timeout,
        )
        return cls(http, session_id_from(payload))

    async def kill(self) -> bool:
        await self._http.request("DELETE", self._path())
        return True

    async def pause(self) -> None:
        await self._http.request("POST", self._path() + "/pause")

    async def resume(self) -> None:
        await self._http.request("POST", self._path() + "/resume")

    def _path(self) -> str:
        return "/v2/agents/sessions/{}".format(self.sandbox_id)


class _SandboxFactory:
    def __init__(self, client: "Client"):
        self._client = client

    async def create(
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
        parent = self._client
        if token is not None or api_key is not None:
            use_token, use_key = token, api_key
        else:
            use_token, use_key = parent.token, parent.api_key
        if api_url is not None or region is not None:
            use_url, use_region = api_url, region
        else:
            use_url, use_region = parent.api_url, parent.region
        return await Sandbox.create(
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
    """Async counterpart of :class:`pydo.sandbox.Client`."""

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
        return "<pydo.sandbox.aio.Client>"


class SandboxHttp:
    def __init__(self, token, api_key, api_url, region, timeout):
        resolved, origin = resolve_connection(token, api_key, api_url, region)
        self._token = resolved
        self._origin = origin
        self._timeout = timeout

    async def request(
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
        client_timeout = aiohttp.ClientTimeout(
            total=self._timeout if timeout is None else timeout
        )
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.request(
                method,
                self._origin + path,
                headers=headers,
                data=data,
                json=json_payload,
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    if response.status in (401, 403):
                        raise AuthenticationError(
                            "authentication failed ({}): {}".format(
                                response.status, text
                            )
                        )
                    if response.status == 404:
                        raise NotFoundError(text)
                    raise SandboxError("HTTP {}: {}".format(response.status, text))
                if not text:
                    return None
                content = response.headers.get("Content-Type", "")
                if "json" in content or text[:1] in ("{", "["):
                    return json.loads(text)
                return text
