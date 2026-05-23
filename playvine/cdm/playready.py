"""
PlayReady CDM wrapper.

Encapsulates every PlayReady-specific quirk:
  - PSSH unwrapping via pyplayready.system.pssh.PSSH.wrm_headers[0]
  - License-response bytes->str decode (PR licenses are XML strings)
  - Key attribute name (k.key_id, not k.kid as in Widevine)
  - No service certificate step (PR doesn't have one)
"""
import logging

from pyplayready.system.pssh import PSSH

from playvine.cdm.base import BaseCDM

log = logging.getLogger("PlayReadyCDM")


class PlayReadyCDM(BaseCDM):
    """Wraps a pyplayready Cdm (or RemoteCdm) for license acquisition."""

    def get_keys(self, track, service, title) -> list[tuple[str, str]]:
        if not track.psshPR:
            raise RuntimeError("Track has no PlayReady PSSH for the active CDM")

        session_id = self.raw.open()
        log.info(f" + CDM Session: {session_id.hex()}")
        try:
            challenge = self.raw.get_license_challenge(
                session_id, PSSH(track.psshPR).wrm_headers[0]
            )
            license_msg = service.license(
                challenge=challenge,
                title=title,
                track=track,
                session_id=session_id,
            )
            assert license_msg, "Empty license response"
            if isinstance(license_msg, bytes):
                license_msg = license_msg.decode("utf-8")
            self.raw.parse_license(session_id, license_msg)
            return [
                (str(k.key_id).replace("-", ""), k.key.hex())
                for k in self.raw.get_keys(session_id)
            ]
        finally:
            self.raw.close(session_id)
