"""
Widevine CDM wrapper.

Encapsulates every Widevine-specific quirk:
  - PSSH wrapping via pywidevine.PSSH
  - Service certificate exchange (privacy mode)
  - JSON / base64 license-response unwrapping (some services wrap it)
  - Content-key filtering by k.type == "CONTENT"
  - KID normalization (dashes stripped)
"""
import base64
import json
import logging

from pywidevine import PSSH

from playvine.cdm.base import BaseCDM

log = logging.getLogger("WidevineCDM")


def _unwrap_license(data: bytes) -> list[bytes]:
    """
    Return candidate license bytes in order of likelihood:
      1. Raw bytes as-is (most common)
      2. JSON  {"license": "<base64>"}  (some proxies/services)
      3. Base64-encoded raw bytes       (rare)
    """
    candidates: list[bytes] = [data]
    try:
        j = json.loads(data)
        for key in ("license", "licenseData", "license_message", "response"):
            if key in j:
                candidates.append(base64.b64decode(j[key]))
                break
    except Exception:
        pass
    try:
        candidates.append(base64.b64decode(data))
    except Exception:
        pass
    return candidates


class WidevineCDM(BaseCDM):
    """Wraps a pywidevine Cdm (or RemoteCdm) for license acquisition."""

    def get_keys(self, track, service, title) -> list[tuple[str, str]]:
        if not track.psshWV:
            raise RuntimeError("Track has no Widevine PSSH for the active CDM")

        session_id = self.raw.open()
        log.info(f" + CDM Session: {session_id.hex()}")
        try:
            # Service certificate (privacy-mode handshake)
            self.raw.set_service_certificate(
                session_id,
                service.certificate(
                    challenge=self.raw.service_certificate_challenge,
                    title=title,
                    track=track,
                    session_id=session_id,
                ) or self.raw.common_privacy_cert,
            )

            # License challenge -> service exchange
            license_msg = service.license(
                challenge=self.raw.get_license_challenge(
                    session_id=session_id,
                    pssh=PSSH(track.psshWV),
                ),
                title=title,
                track=track,
                session_id=session_id,
            )
            assert license_msg, "Empty license response"
            log.debug(f" + License response ({len(license_msg)} bytes): {license_msg[:120]!r}")

            # Some license servers wrap the response in JSON or base64.
            candidates = _unwrap_license(license_msg)
            last_err = None
            parsed = False
            for attempt, candidate in enumerate(candidates, 1):
                try:
                    self.raw.parse_license(session_id, candidate)
                    if attempt > 1:
                        log.debug(f" + Parsed license on unwrap attempt #{attempt}")
                    parsed = True
                    break
                except Exception as parse_err:
                    last_err = parse_err
            if not parsed:
                raise ValueError(
                    f"Could not parse license response. "
                    f"Raw ({len(license_msg)} B): {license_msg[:80]!r}"
                ) from last_err

            return [
                (str(k.kid).replace("-", ""), k.key.hex())
                for k in self.raw.get_keys(session_id)
                if k.type == "CONTENT"
            ]
        finally:
            self.raw.close(session_id)
