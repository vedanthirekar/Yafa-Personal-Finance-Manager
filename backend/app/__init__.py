import sys
from pathlib import Path

# Repo root holds the legacy speechlib.py/nlp.py modules reused by
# services/speech.py and services/nlp_extract.py -- make sure it's importable
# regardless of how uvicorn was launched (module mode vs console-script).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
