"""Shared paths and secret loading.

Deliberately tiny and dependency free. Secrets live in PROJECT_ROOT/.env,
which is gitignored. Nothing in this module ever prints a value.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"


def load_env(path=ENV_PATH):
    """Read KEY=VALUE lines from .env into os.environ.

    Existing environment variables win, so an exported value can override
    the file without editing it.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require(name):
    """Return the named secret, or exit with a message that names the file."""
    load_env()
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing {name}. Add it to {ENV_PATH}.")
    return value


def optional(name):
    """Return the named secret, or None if it is not configured."""
    load_env()
    value = os.environ.get(name)
    return value if value else None
