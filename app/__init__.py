"""Loads a local .env file (if present) so `uvicorn app.main:app` just works.

Kept to a few lines instead of a python-dotenv dependency: KEY=VALUE lines,
'#' comments, no interpolation. Real deployments set env vars in the host.
"""

import os
from pathlib import Path

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
