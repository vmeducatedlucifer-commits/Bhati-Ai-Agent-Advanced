import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Point every test run at a throwaway data directory before app.core.config is imported.
_TMP = tempfile.mkdtemp(prefix="bhati-test-")
os.environ.setdefault("DATA_DIR", _TMP)
os.environ.setdefault("WORKSPACE_ROOT", os.path.join(_TMP, "workspaces"))
os.environ.setdefault("SANDBOX_BACKEND", "local")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP}/test.db")
