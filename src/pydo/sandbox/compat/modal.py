# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""Modal-shaped sandbox that runs on DigitalOcean.

::

    from pydo.sandbox.compat.modal import Sandbox

    sb = Sandbox.create(name="pydo")
    proc = sb.exec("echo", "hi")
    print(proc.stdout.read())
    sb.terminate()

``exec`` waits until the command finishes, then returns a process whose
``stdout.read()`` and ``stderr.read()`` are the captured output. A non-zero
exit does not raise; ``returncode`` is the exit code. ``image``, ``app``,
``cpu``, ``memory``, ``gpu``, ``secrets``, ``volumes``, and a sandbox lifetime
``timeout`` raise :class:`~pydo.sandbox.errors.SandboxError`.
"""
from __future__ import annotations

from typing import Optional

from pydo.sandbox import Sandbox as _Sandbox
from pydo.sandbox.errors import CommandExitError, SandboxError

__all__ = ["Sandbox"]


class _Stream:
    """Finished stdout or stderr. ``read`` returns the whole capture."""

    def __init__(self, data: str, text: bool):
        self._data = data
        self._text = text

    def read(self):
        if self._text:
            return self._data
        return self._data.encode("utf-8")


class Process:
    """Result of :meth:`Sandbox.exec`. The command has already finished."""

    def __init__(self, exit_code: int, stdout: str, stderr: str, text: bool):
        self.returncode = exit_code
        self.stdout = _Stream(stdout, text)
        self.stderr = _Stream(stderr, text)

    def wait(self) -> int:
        """Return the exit code. The command has already finished."""
        return self.returncode

    def poll(self) -> int:
        """Return the exit code. The command has already finished."""
        return self.returncode


class Sandbox:
    """One DigitalOcean sandbox, addressed with Modal's method names."""

    def __init__(self, inner: _Sandbox):
        self._inner = inner
        self.sandbox_id = inner.sandbox_id

    @classmethod
    def create(
        cls,
        *command,
        name: Optional[str] = None,
        size: Optional[str] = None,
        image=None,
        app=None,
        cpu=None,
        memory=None,
        gpu=None,
        secrets=None,
        volumes=None,
        timeout=None,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        api_url: Optional[str] = None,
        region: Optional[str] = None,
    ) -> "Sandbox":
        """Create a sandbox. Call :meth:`exec` to run a command."""
        if command:
            raise SandboxError("Sandbox.create does not start a command; call exec()")
        unsupported = (
            ("image", image),
            ("app", app),
            ("cpu", cpu),
            ("memory", memory),
            ("gpu", gpu),
            ("secrets", secrets),
            ("volumes", volumes),
        )
        for label, value in unsupported:
            if value:
                raise SandboxError(
                    "{} is not supported on the DigitalOcean sandbox".format(label)
                )
        if timeout is not None:
            raise SandboxError(
                "sandbox lifetime timeout is not supported; the session stays "
                "up until terminate(). Pass timeout to exec() for a command "
                "deadline"
            )
        inner = _Sandbox.create(
            name=name,
            size=size,
            api_key=api_key,
            token=token,
            api_url=api_url,
            region=region,
        )
        return cls(inner)

    def exec(self, *args, workdir=None, timeout=None, env=None, text: bool = True):
        """Run ``args`` as argv and wait. A non-zero exit does not raise."""
        if env:
            raise SandboxError(
                "env is not supported: the public exec body has no env field"
            )
        if not args:
            raise SandboxError("exec requires a command")
        try:
            result = self._inner.commands.run(list(args), cwd=workdir, timeout=timeout)
        except CommandExitError as exc:
            return Process(exc.exit_code, exc.stdout, exc.stderr, text)
        return Process(result.exit_code, result.stdout, result.stderr, text)

    def terminate(self) -> bool:
        """Delete the session."""
        return self._inner.kill()
