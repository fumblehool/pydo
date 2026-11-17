# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""E2B-shaped sandbox that runs on DigitalOcean.

::

    from pydo.sandbox.compat.e2b import Sandbox

    sb = Sandbox.create(template="base")
    print(sb.commands.run("echo hi").stdout)
    sb.kill()

``template="base"`` selects the default DigitalOcean sandbox. Any other
template raises :class:`~pydo.sandbox.errors.SandboxError`. A sandbox lifetime
``timeout``, ``metadata``, ``envs``, and ``secure`` also raise. Command
``timeout`` is the exec deadline. A non-zero exit raises
:class:`~pydo.sandbox.errors.CommandExitError`.
"""
from __future__ import annotations

from typing import Optional

from pydo.sandbox import Sandbox as _Sandbox
from pydo.sandbox.errors import SandboxError

__all__ = ["Sandbox"]

_BASE_TEMPLATE = "base"


class Commands:
    """``sb.commands.run``, matching the E2B commands handle."""

    def __init__(self, commands):
        self._commands = commands

    def run(
        self,
        cmd,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        envs=None,
        background: bool = False,
        stdin=None,
        user=None,
        on_stdout=None,
        on_stderr=None,
    ):
        """Run a command and wait. A string is ``sh -c``. A list is the argv."""
        if user is not None:
            raise SandboxError("user is not supported on the DigitalOcean sandbox")
        if on_stdout is not None or on_stderr is not None:
            raise SandboxError(
                "on_stdout and on_stderr are not supported; "
                "commands.run returns the captured output"
            )
        return self._commands.run(
            cmd,
            cwd=cwd,
            timeout=timeout,
            envs=envs,
            background=background,
            stdin=stdin,
        )


class Sandbox:
    """One DigitalOcean sandbox, addressed with E2B's method names."""

    def __init__(self, inner: _Sandbox):
        self._inner = inner
        self.sandbox_id = inner.sandbox_id
        self.commands = Commands(inner.commands)

    @classmethod
    def create(
        cls,
        template: Optional[str] = None,
        *,
        name: Optional[str] = None,
        size: Optional[str] = None,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        api_url: Optional[str] = None,
        region: Optional[str] = None,
        metadata=None,
        envs=None,
        timeout=None,
        secure=None,
    ) -> "Sandbox":
        """Create a sandbox. ``template`` must be omitted or ``"base"``."""
        if template not in (None, _BASE_TEMPLATE):
            raise SandboxError(
                "E2B template {!r} is not available; DigitalOcean sandboxes "
                "use size=".format(template)
            )
        if metadata:
            raise SandboxError("metadata is not supported on the DigitalOcean sandbox")
        if envs:
            raise SandboxError(
                "envs is not supported: the public exec body has no env field"
            )
        if timeout is not None:
            raise SandboxError(
                "sandbox lifetime timeout is not supported; the session stays "
                "up until kill(). Pass timeout to commands.run() for a command "
                "deadline"
            )
        if secure is not None:
            raise SandboxError("secure is not supported on the DigitalOcean sandbox")
        inner = _Sandbox.create(
            name=name,
            size=size,
            api_key=api_key,
            token=token,
            api_url=api_url,
            region=region,
        )
        return cls(inner)

    def kill(self) -> bool:
        """Delete the session."""
        return self._inner.kill()

    def pause(self) -> None:
        self._inner.pause()

    def resume(self) -> None:
        self._inner.resume()
