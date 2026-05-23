"""
Service plugin directory (auto-discovered at startup).

Layout: every service lives in its own subfolder under this directory.
The subfolder contains either:

  * an `__init__.py` (unshackle-style folder package), or
  * a single `.py` file (vinetrimmer-style standalone script)

Plus an optional `config.yaml` (or `config.yml`) next to it for per-service
settings (proxies, device specs, endpoints, etc).

Example layouts:

  playvine/services/AMZN/
      __init__.py     # subclass of BaseService named AMZN
      config.yaml

  playvine/services/hbomax/
      hbomax.py       # subclass of BaseService named HBOMax
      config.yaml

The folder name is purely organisational. The actual CLI invocation tag
comes from the class's ALIASES list. So a folder named anything can be
invoked by any alias declared on its service class.

Files starting with "_" are skipped. The reserved file `converter.py`
at the root of this directory (if present) is also skipped by the loader
because it is a utility script, not a service.
"""
import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# canonical class name -> list of CLI aliases
SERVICE_MAP: dict[str, list[str]] = {}

# canonical class name -> the class object itself
_SERVICE_CLASSES: dict[str, type] = {}

# canonical class name -> Path to the service's folder
_SERVICE_FOLDERS: dict[str, Path] = {}

_here = Path(__file__).resolve().parent


def _discover() -> None:
    """
    Walk every subfolder, locate one service module inside it, import it,
    and register any BaseService subclass it defines.
    """
    from playvine.services.BaseService import BaseService  # local import: avoid circular

    for entry in sorted(_here.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name == "__pycache__":
            continue

        # Pick a module to import. Prefer __init__.py if present (unshackle
        # style). Otherwise fall back to a single .py file in the folder
        # (vinetrimmer style and PlayVine-native default).
        candidates: list[str] = []
        if (entry / "__init__.py").is_file():
            candidates.append(f"playvine.services.{entry.name}")
        for py_file in sorted(entry.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            if py_file.name.startswith("_"):
                continue
            candidates.append(f"playvine.services.{entry.name}.{py_file.stem}")

        if not candidates:
            log.debug(f"skipping {entry.name}: no python module inside")
            continue

        loaded = None
        for module_name in candidates:
            try:
                loaded = importlib.import_module(module_name)
                break
            except Exception as exc:
                log.warning(f" ! could not import {module_name}: {exc}")
                continue

        if loaded is None:
            continue

        registered = False
        for attr_name in dir(loaded):
            obj = getattr(loaded, attr_name)
            if not inspect.isclass(obj):
                continue
            if not issubclass(obj, BaseService) or obj is BaseService:
                continue
            # Only classes actually defined in this module (avoid picking
            # up BaseService re-exports or anything imported in).
            if not obj.__module__.startswith(loaded.__name__):
                continue

            class_name = obj.__name__
            aliases = list(getattr(obj, "ALIASES", []))
            SERVICE_MAP[class_name] = aliases
            _SERVICE_CLASSES[class_name] = obj
            _SERVICE_FOLDERS[class_name] = entry
            # Expose as an attribute of this package so callers that
            # iterate services.__dict__ can find it.
            setattr(sys.modules[__name__], class_name, obj)
            registered = True

        if not registered:
            log.warning(f" ! no BaseService subclass found in folder '{entry.name}'")


def get_service_key(query: str) -> Optional[str]:
    """Resolve a CLI name or alias to its canonical service class name."""
    if not query:
        return None
    q = query.lower()
    for key, aliases in SERVICE_MAP.items():
        if q == key.lower() or q in [a.lower() for a in aliases]:
            return key
    return None


def get_service_class(name: str) -> Optional[type]:
    """Return the service class object for a canonical class name."""
    return _SERVICE_CLASSES.get(name)


def get_service_folder(name_or_alias: str) -> Optional[Path]:
    """Return the folder for a service by canonical name or alias."""
    key = get_service_key(name_or_alias)
    if key is None:
        return None
    return _SERVICE_FOLDERS.get(key)


_discover()
