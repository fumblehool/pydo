# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""Errors for the hand-written sandbox client. ``make clean`` keeps this package."""


class SandboxError(Exception):
    """Base error for the sandbox client."""


class AuthenticationError(SandboxError):
    """The call had no token, or the API rejected it."""


class NotFoundError(SandboxError):
    """The API returned 404."""


class CommandExitError(SandboxError):
    """``commands.run`` finished with a non-zero exit code.

    ``stdout`` and ``stderr`` are the output captured before the process exited.
    """

    def __init__(self, exit_code, stdout, stderr):
        super().__init__("command exited with code {}".format(exit_code))
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
