"""
Base CDM interface.

Each supported DRM scheme has a subclass of `BaseCDM` that wraps the
underlying vendor CDM object (pywidevine.Cdm, pyplayready.Cdm, etc.)
and exposes a uniform `get_keys()` method. Callers stay DRM-agnostic.
"""
from abc import ABC, abstractmethod


class BaseCDM(ABC):
    """
    Abstract DRM-agnostic CDM wrapper.

    Subclasses wrap a vendor CDM and hide every DRM-specific quirk
    (PSSH wrapping, service certificate exchange, license parsing,
    key extraction, attribute-name differences) behind a single method.

    Attributes:
        raw: The wrapped vendor CDM object.
    """

    def __init__(self, raw_cdm):
        self.raw = raw_cdm

    @abstractmethod
    def get_keys(self, track, service, title) -> list[tuple[str, str]]:
        """
        Open a CDM session, exchange a license with the service, and
        return the resulting content keys.

        Parameters:
            track:   A playvine Track instance with PSSH data populated.
            service: The active service instance, used for the license
                     exchange and (for Widevine) the service certificate.
            title:   The Title context for the request - passed through
                     to service callbacks so per-title logic can apply.

        Returns:
            A list of (kid_hex, key_hex) tuples - one entry per content
            key. `kid_hex` is a lowercase hex string with dashes stripped.

        Raises:
            RuntimeError: when the track lacks the PSSH this CDM expects,
                          or when license parsing fails.
        """
        ...
