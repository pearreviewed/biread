"""Make `biread_sync` importable however the suite is started.

The sync service is not installed as a package — it is deployed by copying the
directory — so its tests find it only if this directory is on the path. Running
`python -m pytest` puts it there by accident, the bare `pytest` console script
does not, and that difference is exactly what kept CI red for two days on the
reader tests. Stating it here means the suite runs the same way under either.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
