"""
Auto-import every ``*_agent`` submodule so that each agent's
``@AgentRegistry.register(...)`` decorator runs at package-import time.

Importing ``agents`` anywhere in the codebase is enough to populate the
registry; you do not need to reference individual agent modules.
"""
from importlib import import_module
from pathlib import Path

_here = Path(__file__).resolve().parent
for _path in _here.glob("*_agent.py"):
    if _path.name == "base_agent.py":
        continue
    import_module(f"{__name__}.{_path.stem}")
del _here, _path, import_module, Path