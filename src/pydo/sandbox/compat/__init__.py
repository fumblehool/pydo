# ------------------------------------
# Copyright (c) DigitalOcean.
# Licensed under the Apache-2.0 License.
# ------------------------------------
"""Factories whose methods match another sandbox SDK.

``Sandbox.compat("e2b")`` and ``Sandbox.compat("modal")`` call :func:`factory`.
The returned class talks to DigitalOcean. See :mod:`pydo.sandbox.compat.e2b`
and :mod:`pydo.sandbox.compat.modal`.
"""
from __future__ import annotations

from pydo.sandbox.errors import SandboxError

__all__ = ["factory"]


def factory(api: str):
    """Return the sandbox class for ``api`` (``"e2b"`` or ``"modal"``)."""
    key = (api or "").strip().lower()
    if key == "e2b":
        from pydo.sandbox.compat.e2b import Sandbox

        return Sandbox
    if key == "modal":
        from pydo.sandbox.compat.modal import Sandbox

        return Sandbox
    raise SandboxError(
        "unknown sandbox api {!r}; expected 'e2b' or 'modal'".format(api)
    )
