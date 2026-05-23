import logging
import re
import requests


class BaseService:
    """
    Base class for all PlayVine service plugins.

    To add a service:
      1. Create a .py file in this directory, e.g. playvine/services/MyService.py
      2. Subclass BaseService and set ALIASES = ["MSV", "myservice"]
      3. Add a @staticmethod cli() Click command that returns an instance of your class
      4. Implement get_titles(), get_tracks(), and license()

    The services directory is scanned automatically at startup — no registration needed.
    """

    # CLI names / shortcuts recognised for this service (case-insensitive).
    # The first entry is treated as the canonical short tag.
    # Example: ALIASES = ["AMZN", "amazon", "amzn"]
    ALIASES: list = []

    # Regex pattern(s) used to detect this service from a URL or title ID.
    # Should contain a named group (?P<id>...) for the title ID, and optionally
    # (?P<type>...) for movie/series disambiguation.
    TITLE_RE = []

    # Set to True when this service uses multiple KID/key pairs per title
    # (e.g. Disney+, Hulu). dl.py will always fetch fresh keys from the CDM
    # and use shaka-packager with per-label key args for decryption.
    MULTI_KEY: bool = False

    # Set to True when audio tracks must be downloaded before video tracks
    # because auth tokens expire during large video downloads (e.g. Hotstar).
    DOWNLOAD_AUDIO_FIRST: bool = False

    # Set to True when video tracks must always be treated as encrypted even
    # if the manifest does not mark them as such (e.g. Apple TV+, iTunes).
    FORCE_ENCRYPT_VIDEO: bool = False

    # Downloader to use for this service's tracks. Defaults to "aria2c".
    # Set to "m3u8dl" for services where N_m3u8DL-RE handles the manifest better
    # (e.g. HLS with complex segmentation), or "saldl" for services that benefit
    # from saldl's chunking. ISM-descriptor tracks always use m3u8dl regardless,
    # and TextTrack downloads always use aria2c regardless.
    DOWNLOADER: str = "aria2c"

    def __init__(self, ctx, **kwargs):
        """
        Initialise from a Click context (ctx) produced by the service's cli() command.

        ctx.obj is a ContextData with:
          .config      — service-specific YAML config dict
          .cdm         — pywidevine Cdm or pyplayready Cdm instance
          .cookies     — MozillaCookieJar or None
          .credentials — Credential or None
          .profile     — profile name string or None
        """
        obj = ctx.obj if ctx.obj else None

        self.config = (obj.config if obj else {}) or {}
        self.cdm = obj.cdm if obj else None
        self.profile = obj.profile if obj else None
        self.credentials = obj.credentials if obj else None

        # Build a requests.Session pre-loaded with the profile's cookies.
        # self.cookies is also kept as a direct attribute for old scripts
        # script compatibility (old scripts accessed cookies directly).
        self.cookies = obj.cookies if obj else None
        self.session = requests.Session()
        if self.cookies:
            self.session.cookies.update(self.cookies)

        self.log = logging.getLogger(self.__class__.__name__)

        # Parse the title ID from the title argument
        title_arg = kwargs.get("title") or ""
        m = self._parse_title_re(title_arg)
        self.title = m.get("id", title_arg) if m else title_arg

    # Helper utilities
    def _parse_title_re(self, raw: str) -> "dict | None":
        """Return the first TITLE_RE match as a groupdict, or None."""
        patterns = self.TITLE_RE
        if isinstance(patterns, str):
            patterns = [patterns]
        for pattern in patterns:
            m = re.search(pattern, raw or "")
            if m:
                return m.groupdict()
        return None

    def parse_title(self, ctx, raw: str) -> dict:
        """
        Old scripts compatible helper: parse a title URL/ID and return a groupdict.
        Also sets self.title to the extracted 'id' group.
        """
        result = self._parse_title_re(raw) or {"id": raw}
        self.title = result.get("id", raw)
        return result

    def _is_playready(self) -> bool:
        """
        Return True when the active CDM is a PlayReady CDM.

        Old scripts checked CDM type with:
            from vinetrimmer.utils.widevine.device import LocalDevice
            if self.cdm.device.type == LocalDevice.Types.PLAYREADY: ...

        In PlayVine the CDM is a pywidevine.Cdm or pyplayready.cdm.Cdm object,
        so the device-type attribute is no longer accessible that way.
        Use this method instead in any service script:
            if self._is_playready(): ...
        """
        return bool(self.cdm) and "playready" in type(self.cdm).__module__.lower()

    # Interfaces
    def get_titles(self):
        """Return a list of Title objects for the requested content."""
        raise NotImplementedError

    def get_tracks(self, title):
        """Return a list of Track objects for the given Title."""
        raise NotImplementedError

    def get_chapters(self, title):
        """Return a list of chapter objects for the given Title. Optional."""
        return []

    def certificate(self, **kwargs):
        """Return a service certificate for Widevine, or None to use the common cert."""
        return None

    def license(self, **kwargs):
        """Exchange a license challenge for a license response."""
        raise NotImplementedError