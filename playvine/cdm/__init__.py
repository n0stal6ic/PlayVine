"""
DRM-agnostic CDM layer.

Public API:
    - BaseCDM:         abstract interface every DRM wrapper implements
    - WidevineCDM:     pywidevine wrapper
    - PlayReadyCDM:    pyplayready wrapper
    - wrap_cdm(raw):   factory — returns the right BaseCDM subclass for
                       the given vendor CDM instance
"""
from playvine.cdm.base import BaseCDM
from playvine.cdm.widevine import WidevineCDM
from playvine.cdm.playready import PlayReadyCDM


def wrap_cdm(raw_cdm) -> BaseCDM:
    """
    Wrap a raw vendor CDM (pywidevine.Cdm / pyplayready.Cdm — including
    their RemoteCdm variants) in the matching BaseCDM subclass.

    Detection is by source module, matching the pattern already used by
    BaseService._is_playready(). This survives attribute renames in the
    underlying libraries and gives a clear TypeError for unknown CDMs.
    """
    module = type(raw_cdm).__module__.lower()
    if "pywidevine" in module:
        return WidevineCDM(raw_cdm)
    if "pyplayready" in module:
        return PlayReadyCDM(raw_cdm)
    raise TypeError(
        f"Unknown CDM type: {type(raw_cdm).__name__} "
        f"from module {type(raw_cdm).__module__}"
    )


__all__ = ["BaseCDM", "WidevineCDM", "PlayReadyCDM", "wrap_cdm"]
