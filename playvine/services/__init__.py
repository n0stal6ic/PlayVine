"""
Service plugin directory (auto-discovered at startup)

To add a service:
  1. Create a .py file in this directory (e.g. MyService.py)
  2. Subclass BaseService and set ALIASES ["MSV", "myservice"]
"""
import importlib
import inspect
import logging
import os
import sys

log = logging.getLogger(__name__)

# Populated automatically below (Maps class name to a list of aliases)
SERVICE_MAP: dict[str, list[str]] = {}

# Populated automatically (Maps class name to the class object itself)
_SERVICE_CLASSES: dict[str, type] = {}

_here = os.path.dirname(__file__)


def _discover():
    """Scan this directory and import every BaseService subclass found."""
    from playvine.services.BaseService import BaseService  # local import to avoid circular

    for fname in sorted(os.listdir(_here)):
        if fname.startswith("_") or not fname.endswith(".py"):
            continue
        if fname == "BaseService.py":
            continue

        module_name = f"playvine.services.{fname[:-3]}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            log.warning(f" ! Failed to import service module '{fname}': {exc}")
            continue

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseService)
                and obj is not BaseService
                and obj.__module__ == module_name  # Only classes defined in this file
            ):
                class_name = obj.__name__
                aliases = list(getattr(obj, "ALIASES", []))
                SERVICE_MAP[class_name] = aliases
                _SERVICE_CLASSES[class_name] = obj
                # Also expose the class as a module attribute so load_services()
                # can find it via services.__dict__
                setattr(sys.modules[__name__], class_name, obj)


def get_service_key(query: str) -> "str | None":
    """Return the canonical service class name for a CLI name or alias, or None."""
    if not query:
        return None
    q = query.lower()
    for key, aliases in SERVICE_MAP.items():
        if q == key.lower() or q in [a.lower() for a in aliases]:
            return key
    return None


def get_service_class(name: str) -> "type | None":
    """Return the service class object for a canonical class name, or None."""
    return _SERVICE_CLASSES.get(name)


# Run discovery when this package is imported
_discover()