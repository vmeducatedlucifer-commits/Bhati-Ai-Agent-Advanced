"""Minimal environment for child processes (sandboxes, MCP stdio servers).

Passing the whole host env (`os.environ`) hands every secret on the box —
SECRET_KEY, SMTP_PASS, provider tokens — to agent commands and third-party
MCP packages, where one `printenv` exfiltrates them to the model. Build the
child env from this allowlist instead; per-call extras still win.
"""

from __future__ import annotations

import os

_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LANGUAGE",
    "TZ",
    "TMPDIR",
    "TEMP",
    "TMP",
    "NODE_PATH",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "NO_COLOR",
    "TERM",
    # Windows local-dev basics (harmless on Linux).
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
)


def sandbox_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Host env reduced to non-secret basics, merged over by `extra`."""
    env = {key: os.environ[key] for key in _ALLOWLIST if key in os.environ}
    if extra:
        env.update({k: v for k, v in extra.items() if isinstance(v, str)})
    return env
