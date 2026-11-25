"""Lets the tests import the engine on its own, as ``engine``.

The engine needs neither Home Assistant nor the Home Assistant package. It
is loaded here by its folder, not by putting the integration's folder on the
import path: that folder holds files named after Home Assistant's platforms,
such as ``calendar.py``, which would hide Python's own modules of the same
name.
"""

import importlib.util
import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "custom_components" / "ryton_home_automations" / "engine"

if "engine" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "engine", _ENGINE / "__init__.py", submodule_search_locations=[str(_ENGINE)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["engine"] = _module
    _spec.loader.exec_module(_module)
