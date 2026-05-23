"""
dl.py — PlayVine unified download command.

  - Proper CDM type detection via isinstance() instead of dir() heuristics
  - Key retrieval, decryption, and mux phases extracted into helper functions
  - Correct session_id scoping (no leaking across tracks)
  - Multi-key content handled via service MULTI_KEY class attribute
  - Audio language fallback when original language cannot be detected
  - ISM Atmos fixup and DV+HDR hybrid creation preserved
  - Cookie save on every licensing call
"""
import base64
import html
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Optional
import click
import requests
import urllib3
from langcodes import Language
from pymediainfo import MediaInfo
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playvine import services
from playvine.config import Config, config, credentials, directories, filenames
from playvine.objects import AudioTrack, Credential, TextTrack, Title, Titles, VideoTrack
from playvine.objects.tracks import Track
from playvine.objects.vaults import InsertResult, Vault, Vaults
from playvine.utils import is_close_match
from playvine.utils.click import (
    AliasedGroup, ContextData,
    acodec_param, language_param, quality_param,
    range_param, vcodec_param, wanted_param,
)
from playvine.utils.collections import as_list, merge_dict
from playvine.utils.io import load_yaml
from pywidevine import Device as WVDevice, Cdm as WVCdm, RemoteCdm as WVRemoteCdm
from pywidevine import PSSH as PSSHWV
from pyplayready.cdm import Cdm as PRCdm
from pyplayready import Device as PRDevice
from pyplayready.system.pssh import PSSH as PRPSSH
from pyplayready.crypto.ecc_key import ECCKey
from pyplayready.system.bcert import Certificate
from Crypto.Random import get_random_bytes

log = logging.getLogger("dl")


def reprovision_prd(prd_path: Path) -> None:
    """
    Reprovision a PlayReady device by generating fresh leaf cert + keys.
    Only works on PRD v3+.  Overwrites the file.
    """
    if not prd_path.is_file():
        raise FileNotFoundError(f"PRD not found: {prd_path}")

    device = PRDevice.load(prd_path)
    if device.group_key is None:
        raise ValueError("Device does not support reprovisioning (needs v3+ with group_key)")

    device.group_certificate.remove(0)
    enc_key = ECCKey.generate()
    sig_key = ECCKey.generate()
    device.encryption_key = enc_key
    device.signing_key = sig_key

    new_cert = Certificate.new_leaf_cert(
        cert_id=get_random_bytes(16),
        security_level=device.group_certificate.get_security_level(),
        client_id=get_random_bytes(16),
        signing_key=sig_key,
        encryption_key=enc_key,
        group_key=device.group_key,
        parent=device.group_certificate,
    )
    device.group_certificate.prepend(new_cert)
    prd_path.write_bytes(device.dumps())


def get_cdm(service: str, profile: Optional[str] = None, cdm_name: Optional[str] = None):
    """
    Resolve and return a CDM device for the given service.
    Precedence: explicit --cdm override -> service config -> playvine.yml default.
    Raises ValueError or FileNotFoundError on failure.
    """
    if not cdm_name:
        cdm_name = config.cdm.get(service) or config.cdm.get("default")
    if not cdm_name:
        raise ValueError("No CDM configured in playvine.yml (set cdm.default)")
    if isinstance(cdm_name, dict):
        if not profile:
            raise ValueError("CDM config uses profiles but no --profile was given")
        cdm_name = cdm_name.get(profile) or config.cdm.get("default")
        if not cdm_name:
            raise ValueError(f"No CDM mapped for profile {profile!r}")

    devices_dir = directories.devices

    # PlayReady PRD
    prd_path = Path(os.path.join(devices_dir, f"{cdm_name}.prd"))
    if prd_path.is_file():
        age = int(time.time()) - int(prd_path.stat().st_mtime)
        if age > 160_000:  # ~2 days
            try:
                reprovision_prd(prd_path)
                log.info(f" + Reprovisioned PlayReady device: {cdm_name}")
            except Exception as e:
                log.warning(f" ! Reprovision failed, using existing device: {e}")
        return PRDevice.load(prd_path)

    # Widevine WVD
    wvd_path = os.path.join(devices_dir, f"{cdm_name}.wvd")
    if os.path.isfile(wvd_path):
        return WVDevice.load(wvd_path)

    # Directory Widevine
    dir_path = os.path.join(devices_dir, cdm_name)
    if os.path.isdir(dir_path):
        try:
            return WVDevice.from_dir(dir_path)
        except Exception:
            pass

    # Remote CDM API
    cdm_api = next((x for x in config.cdm_api if x.get("name") == cdm_name), None)
    if cdm_api:
        try:
            return WVRemoteCdm(**cdm_api)
        except Exception:
            from playvine.utils.widevine.device import RemoteDevice
            return RemoteDevice(**cdm_api)

    raise ValueError(f"CDM device {cdm_name!r} not found in {devices_dir!r}")


def get_service_config(service: str) -> dict:
    cfg = load_yaml(filenames.service_config.format(service=service.lower())) or {}
    user_cfg = (
        load_yaml(filenames.user_service_config.format(service=service.lower()))
        or load_yaml(filenames.user_service_config.format(service=service))
    )
    if user_cfg:
        merge_dict(cfg, user_cfg)
    return cfg


def get_profile(service: str) -> Optional[str]:
    profile = config.profiles.get(service)
    if profile is False:
        return None
    if not profile:
        profile = config.profiles.get("default")
    if not profile:
        raise ValueError(f"No profile defined for '{service}' in config.")
    return profile


def get_cookie_jar(service: str, profile: str) -> Optional[MozillaCookieJar]:
    for path in [
        os.path.join(directories.cookies, service.lower(), f"{profile}.txt"),
        os.path.join(directories.cookies, service, f"{profile}.txt"),
    ]:
        if os.path.isfile(path):
            jar = MozillaCookieJar(path)
            with open(path, "r+", encoding="utf-8") as fd:
                unescaped = html.unescape(fd.read())
                fd.seek(0)
                fd.truncate()
                fd.write(unescaped)
            jar.load(ignore_discard=True, ignore_expires=True)
            return jar
    return None


def save_cookies(service_name: str, service, profile: str) -> None:
    if not profile:
        return
    for path in [
        os.path.join(directories.cookies, service_name.lower(), f"{profile}.txt"),
        os.path.join(directories.cookies, service_name, f"{profile}.txt"),
    ]:
        if os.path.isfile(path):
            jar = MozillaCookieJar(path)
            for cookie in service.session.cookies:
                jar.set_cookie(cookie)
            jar.save(ignore_discard=True, ignore_expires=True)
            return


def get_credentials(service: str, profile: str = "default") -> Optional[Credential]:
    """Get the profile's credentials if available. Returns None if not configured."""
    if not credentials:
        return None
    cred = credentials.get(service, {})
    if isinstance(cred, dict):
        cred = cred.get(profile)
    elif profile != "default":
        return None
    if cred:
        return Credential(*cred) if isinstance(cred, list) else Credential.loads(cred)
    return None



def _retrieve_widevine_keys(ctx, service, title, track) -> list:
    """Open a Widevine CDM session, license, and return [(kid_hex, key_hex), ...]."""
    session_id = ctx.obj.cdm.open()
    log.info(f" + CDM Session: {session_id.hex()}")
    try:
        ctx.obj.cdm.set_service_certificate(
            session_id,
            service.certificate(
                challenge=ctx.obj.cdm.service_certificate_challenge,
                title=title,
                track=track,
                session_id=session_id,
            ) or ctx.obj.cdm.common_privacy_cert,
        )
        license_msg = service.license(
            challenge=ctx.obj.cdm.get_license_challenge(
                session_id=session_id,
                pssh=PSSHWV(track.psshWV),
            ),
            title=title,
            track=track,
            session_id=session_id,
        )
        assert license_msg, "Empty license response"
        log.debug(f" + License response ({len(license_msg)} bytes): {license_msg[:120]!r}")
        # Some license servers wrap response in JSON or base64.
        # Try raw bytes first, then common wrapper formats.
        candidates = list(_unwrap_license(license_msg))
        last_err = None
        parsed = False
        for attempt, candidate in enumerate(candidates, 1):
            try:
                ctx.obj.cdm.parse_license(session_id, candidate)
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
        save_cookies(service.__class__.__name__, service, ctx.obj.profile)
        return [
            (str(k.kid).replace("-", ""), k.key.hex())
            for k in ctx.obj.cdm.get_keys(session_id)
            if k.type == "CONTENT"
        ]
    finally:
        ctx.obj.cdm.close(session_id)


def _unwrap_license(data: bytes):
    """
    Yield candidate license bytes in order of likelihood:
      1. Raw bytes as-is (most common)
      2. JSON  {"license": "<base64>"}  (some proxies/services)
      3. Base64-encoded raw bytes       (rare)
    """
    yield data
    try:
        j = json.loads(data)
        for key in ("license", "licenseData", "license_message", "response"):
            if key in j:
                yield base64.b64decode(j[key])
                break
    except Exception:
        pass
    try:
        yield base64.b64decode(data)
    except Exception:
        pass


def _retrieve_playready_keys(ctx, service, title, track) -> list:
    """Open a PR CDM session, license, and return [(kid_hex, key_hex), ...]."""
    session_id = ctx.obj.cdm.open()
    log.info(f" + CDM Session: {session_id.hex()}")
    try:
        challenge = ctx.obj.cdm.get_license_challenge(
            session_id, PRPSSH(track.psshPR).wrm_headers[0]
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
        ctx.obj.cdm.parse_license(session_id, license_msg)
        save_cookies(service.__class__.__name__, service, ctx.obj.profile)
        return [
            (str(k.key_id).replace("-", ""), k.key.hex())
            for k in ctx.obj.cdm.get_keys(session_id)
        ]
    finally:
        ctx.obj.cdm.close(session_id)


def _get_content_keys(ctx, service, title, track, no_cache: bool, cache: bool):
    """
    Full key resolution chain:
      1. Static key already on the track
      2. Key vault lookup
      3. CDM license (WV or PR, auto-selected)

    Returns (key_for_track, all_content_keys), or (None, None) to signal
    the caller should skip this title (only when cache=True and no key found).
    """
    # Static key
    if track.key:
        log.info(f" + KEY: {track.key} (Static)")
        return track.key, [(track.kid, track.key)]

    # Vault lookup
    if not no_cache:
        cached_key, vault_used = ctx.obj.vaults.get(track.kid, title.id)
        if cached_key:
            log.info(f" + KEY: {cached_key} (From {vault_used.name} {vault_used.type.name} Vault)")
            _propagate_to_other_vaults(
                ctx, service.__class__.__name__, track, cached_key, title.id, vault_used
            )
            return cached_key, [(track.kid, cached_key)]

    if cache:
        return None, None

    # CDM (Detect WV vs PR via hasattr over module string methods)
    is_wv = hasattr(ctx.obj.cdm, "common_privacy_cert")
    if is_wv and track.psshWV:
        content_keys = _retrieve_widevine_keys(ctx, service, title, track)
    elif not is_wv and track.psshPR:
        content_keys = _retrieve_playready_keys(ctx, service, title, track)
    else:
        raise RuntimeError("No matching PSSH for the active CDM type")

    if not content_keys:
        raise RuntimeError("CDM returned no content keys")

    log.info(f" + Obtained {len(content_keys)} content key(s) from CDM")
    for kid, key in content_keys:
        log.info(f"   {kid}:{key}")

    _cache_keys(ctx, service.__class__.__name__, content_keys, title.id)

    track_key = next((k for kid, k in content_keys if kid == track.kid), None)
    if not track_key:
        raise RuntimeError(f"No key matched KID {track.kid!r} in CDM response")
    log.info(f" + KEY: {track_key} (From CDM)")
    return track_key, content_keys


def _propagate_to_other_vaults(ctx, service_name, track, key, title_id, source_vault):
    for vault in ctx.obj.vaults.vaults:
        if vault == source_vault:
            continue
        result = ctx.obj.vaults.insert_key(
            vault, service_name.lower(), track.kid, key, title_id, commit=True
        )
        if result == InsertResult.SUCCESS:
            log.info(f"   Cached to {vault} vault")
        elif result == InsertResult.ALREADY_EXISTS:
            log.debug(f"   Already in {vault} vault")


def _cache_keys(ctx, service_name: str, content_keys: list, title_id: str) -> None:
    for vault in ctx.obj.vaults.vaults:
        cached = already = failed = 0
        for kid, key in content_keys:
            r = ctx.obj.vaults.insert_key(vault, service_name.lower(), kid, key, title_id)
            if r == InsertResult.SUCCESS:
                cached += 1
            elif r == InsertResult.ALREADY_EXISTS:
                already += 1
            else:
                failed += 1
        ctx.obj.vaults.commit(vault)
        log.info(f"   Cached {cached} new / {already} existing in {vault} vault")
        if failed:
            log.warning(f"   {failed} key(s) failed to cache in {vault} vault")



def _decrypt_track(track, service_name: str, content_keys: list, multi_key: bool = False) -> None:
    """Decrypt an encrypted track in-place using shaka-packager or mp4decrypt."""
    if not config.decrypter:
        raise RuntimeError("No decrypter configured in playvine.yml")

    dec = os.path.splitext(track.locate())[0].replace("enc", "dec") + ".mp4"
    os.makedirs(directories.temp, exist_ok=True)

    use_packager = (
        multi_key
        or (config.decrypter == "packager" and track.descriptor != Track.Descriptor.ISM)
    )

    if use_packager:
        platform = {"win32": "win", "darwin": "osx"}.get(sys.platform, sys.platform)
        executable = next(
            (x for x in map(shutil.which, ["shaka-packager", "packager", f"packager-{platform}"]) if x),
            None,
        )
        if not executable:
            raise RuntimeError("shaka-packager / packager binary not found in PATH or ./binaries")

        if multi_key:
            # Multi-key (Label KID/KEYs by index)
            keys_arg = ",".join(
                f"label={i}:key_id={kid}:key={key}"
                for i, (kid, key) in enumerate(content_keys)
            )
        else:
            keys_arg = ",".join([
                f"label=0:key_id={track.kid.lower()}:key={track.key.lower()}",
                # ATV+ Workaround (Zeroed-KID fallback label)
                f"label=1:key_id=00000000000000000000000000000000:key={track.key.lower()}",
            ])

        subprocess.run(
            [
                executable,
                f"input={track.locate()},stream={track.__class__.__name__.lower().replace('track', '')},output={dec}",
                "--enable_raw_key_decryption", "--keys", keys_arg,
                "--temp_dir", directories.temp,
            ],
            check=True,
        )

    else:
        executable = shutil.which("mp4decrypt")
        if not executable:
            raise RuntimeError("mp4decrypt binary not found in PATH or ./binaries")
        subprocess.run(
            [
                executable,
                "--show-progress",
                "--key", f"{track.kid.lower()}:{track.key.lower()}",
                track.locate(), dec,
            ],
            check=True,
        )

    track.swap(dec)



def _run_ccextractor(service, title, track, no_subs: bool) -> None:
    if no_subs:
        return
    log.info("Extracting EIA-608 captions with CCExtractor")
    track_id = f"ccextractor-{track.id}"
    cc_lang = track.language
    try:
        cc = track.ccextractor(
            track_id=track_id,
            out_path=filenames.subtitles.format(id=track_id, language_code=cc_lang),
            language=cc_lang,
            original=False,
        )
    except EnvironmentError:
        log.warning(" - CCExtractor not found, cannot extract captions")
        return
    if cc:
        title.tracks.add(cc)
        log.info(" + Captions extracted")
    else:
        log.info(" + No captions found in stream")



@click.group(
    name="dl",
    short_help="Download from a service.",
    cls=AliasedGroup,
    context_settings=dict(
        help_option_names=["-?", "-h", "--help"],
        max_content_width=116,
        default_map=config.arguments,
    ),
)
@click.option("--debug", is_flag=True, hidden=True)
@click.option("-p", "--profile", type=str, default=None,
              help="Profile to use when multiple profiles are defined for a service.")
@click.option("-q", "--quality", callback=quality_param, default=None,
              help="Download resolution, e.g. 1080, 720, 4K. Defaults to best.")
@click.option("-cr", "--closest-resolution", is_flag=True, default=False,
              help="Use closest available resolution when exact match not found.")
@click.option("-v", "--vcodec", callback=vcodec_param, default="H264",
              help="Video codec. Default: H264.")
@click.option("-a", "--acodec", callback=acodec_param, default=None,
              help="Audio codec preference.")
@click.option("-vb", "--vbitrate", type=str, default=None,
              help="Video bitrate preference. Defaults to max.")
@click.option("-ab", "--abitrate", type=int, default=None,
              help="Audio bitrate preference. Defaults to max.")
@click.option("-ac", "--audio-channels", type=str, default=None,
              help="Audio channel configuration, e.g. '2.0', '5.1', '2.0,5.1'.")
@click.option("-mac", "--max-audio-compatibility", is_flag=True, default=False,
              help="Select multiple audio tracks for broadest device compatibility.")
@click.option("-aa", "--atmos", is_flag=True, default=False,
              help="Prefer Dolby Atmos audio.")
@click.option("-r", "--range", "range_", callback=range_param, default="SDR",
              help="Video range. Default: SDR. Options: SDR, HDR10, HLG, DV, DV+HDR.")
@click.option("-w", "--wanted", callback=wanted_param, default=None,
              help="Episode filter, e.g. S01-S05, S01E01-S02E03. Default: all.")
@click.option("-le", "--latest-episode", is_flag=True, default=False,
              help="Download the most recent episode only.")
@click.option("-al", "--alang", callback=language_param, default="orig",
              help="Audio language(s). Default: orig (original language).")
@click.option("-sl", "--slang", callback=language_param, default="all",
              help="Subtitle language(s). Default: all.")
@click.option("--proxy", type=str, default=None,
              help="Proxy URI or 2-letter country code to look up from config.")
@click.option("-A", "--audio-only", is_flag=True, default=False,
              help="Download audio tracks only.")
@click.option("-S", "--subs-only", is_flag=True, default=False,
              help="Download subtitle tracks only.")
@click.option("-C", "--chapters-only", is_flag=True, default=False,
              help="Download chapters only.")
@click.option("-ns", "--no-subs", is_flag=True, default=False,
              help="Skip subtitle tracks.")
@click.option("-na", "--no-audio", is_flag=True, default=False,
              help="Skip audio tracks.")
@click.option("-nv", "--no-video", is_flag=True, default=False,
              help="Skip video tracks.")
@click.option("-nc", "--no-chapters", is_flag=True, default=False,
              help="Skip chapter tracks.")
@click.option("-ad", "--audio-description", is_flag=True, default=False,
              help="Include audio description (AD) tracks.")
@click.option("--list", "list_", is_flag=True, default=False,
              help="List available and selected tracks without downloading.")
@click.option("--selected", is_flag=True, default=False,
              help="Show only selected tracks (skip the full track listing).")
@click.option("--cdm", type=str, default=None,
              help="Override the CDM device used for decryption.")
@click.option("--keys", is_flag=True, default=False,
              help="Print decryption keys only, do not download.")
@click.option("--cache", is_flag=True, default=False,
              help="Only use key vaults; skip CDM if key is not cached.")
@click.option("--no-cache", is_flag=True, default=False,
              help="Only use the CDM; ignore key vaults.")
@click.option("--no-proxy", is_flag=True, default=False,
              help="Disable all proxy use.")
@click.option("-nm", "--no-mux", is_flag=True, default=False,
              help="Do not mux downloaded tracks into an MKV.")
@click.option("--mux", is_flag=True, default=False,
              help="Force mux even when --audio-only/--subs-only is set.")
@click.option("-ss", "--strip-sdh", is_flag=True, default=False,
              help="Strip SDH formatting from subtitles and convert to CC.")
@click.option("-mf", "--match-forced", is_flag=True, default=False,
              help="Only select forced subtitles matching the audio language.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show selected tracks and predicted output filename without downloading.")
@click.option("-se", "--skip-existing", is_flag=True, default=False,
              help="Skip titles that already exist in the download directory.")
@click.pass_context
def dl(ctx, profile, cdm, *_, **__):
    service_key = ctx.params.get("service_name") or services.get_service_key(ctx.invoked_subcommand)
    if not service_key:
        log.exit(" - Unable to find service")
        return

    try:
        profile = profile or get_profile(service_key)
    except ValueError as e:
        raise log.exit(f" - {e}")

    service_config = get_service_config(service_key)

    vaults = []
    for vault_cfg in config.key_vaults:
        try:
            vaults.append(Config.load_vault(vault_cfg))
        except Exception as e:
            log.error(f" - Failed to load vault {vault_cfg.get('name', '?')!r}: {e}")
    vaults = Vaults(vaults, service=service_key)
    local_vaults = sum(v.type == Vault.Types.LOCAL for v in vaults)
    remote_vaults = sum(v.type == Vault.Types.REMOTE for v in vaults)
    http_vaults = sum(v.type in (Vault.Types.HTTP, Vault.Types.HTTPAPI) for v in vaults)
    log.info(f" + {local_vaults} Local Vault{'' if local_vaults == 1 else 's'}")
    log.info(f" + {remote_vaults} Remote Vault{'' if remote_vaults == 1 else 's'}")
    if http_vaults:
        log.info(f" + {http_vaults} HTTP Vault{'' if http_vaults == 1 else 's'}")

    try:
        device = get_cdm(service_key, profile, cdm)
    except (ValueError, FileNotFoundError) as e:
        raise log.exit(f" - {e}")

    is_pr = isinstance(device, PRDevice)
    if is_pr:
        device_label = device.get_name().replace("_", " ").upper()
        log.info(f" + Loaded PlayReady Device: {device_label} (SL{device.security_level})")
        cdm_obj = PRCdm.from_device(device)
    else:
        device_label = getattr(device, "system_id", device.__class__.__name__)
        log.info(f" + Loaded Widevine Device: {device_label} (L{device.security_level})")
        cdm_obj = WVCdm.from_device(device)

    service_credentials = None
    cookies = None
    if profile:
        cookies = get_cookie_jar(service_key, profile)
        service_credentials = get_credentials(service_key, profile)
        if not cookies and not service_credentials and service_config.get("needs_auth", True):
            raise log.exit(f" - Profile {profile!r} has no cookies or credentials")

    ctx.obj = ContextData(
        config=service_config,
        vaults=vaults,
        cdm=cdm_obj,
        profile=profile,
        cookies=cookies,
        credentials=service_credentials,
    )


@dl.result_callback()
@click.pass_context
def result(
    ctx, service,
    quality, closest_resolution, range_, wanted,
    alang, slang, acodec,
    audio_only, subs_only, chapters_only, audio_description,
    audio_channels, max_audio_compatibility,
    vbitrate, abitrate,
    list_, keys, cache, no_cache,
    no_subs, no_audio, no_video, no_chapters,
    no_mux, mux, selected, latest_episode,
    strip_sdh, match_forced,
    *_, **__,
):
    dry_run = __.get("dry_run", False)

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    service_name = service.__class__.__name__
    log = service.log

    # Attach retry adapter using config values
    network_cfg = getattr(config, "network", None) or {}
    retry_count = int(network_cfg.get("retry_count", 3))
    retry_backoff = float(network_cfg.get("retry_backoff", 0.5))
    if retry_count > 0 and hasattr(service, "session"):
        retry_strategy = Retry(
            total=retry_count,
            backoff_factor=retry_backoff,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        service.session.mount("https://", adapter)
        service.session.mount("http://", adapter)

    # Services with MULTI_KEY=True use multiple KID/KEY pairs per title so always fetch fresh from CDM
    effective_no_cache = no_cache or getattr(service, "MULTI_KEY", False)

    # Resolve proxy: CLI --proxy > service YAML proxy > no proxy
    # --no-proxy clears everything regardless of other settings
    _no_proxy = __.get("no_proxy", False)
    _cli_proxy = __.get("proxy", None)
    _skip_existing = __.get("skip_existing", False)
    if _no_proxy:
        service.session.proxies.clear()
    elif _cli_proxy:
        service.session.proxies.update({"http": _cli_proxy, "https": _cli_proxy})
        log.debug(f" + Proxy (CLI): {_cli_proxy}")
    elif service.config.get("proxy"):
        _svc_proxy = service.config["proxy"]
        service.session.proxies.update({"http": _svc_proxy, "https": _svc_proxy})
        log.debug(f" + Proxy (service config): {_svc_proxy}")

    log.info("Retrieving Titles")
    try:
        titles = Titles(as_list(service.get_titles()))
    except requests.HTTPError as e:
        log.debug(traceback.format_exc())
        raise log.exit(f" - HTTP Error {e.response.status_code}: {e.response.reason}")
    if not titles:
        raise log.exit(" - No titles returned!")
    titles.order()
    titles.print()

    if latest_episode:
        titles = Titles(as_list(titles[-1]))

    for title in titles.with_wanted(wanted):
        if title.type == Title.Types.TV:
            log.info("Getting tracks for {t} S{s:02}E{e:02}{n} [{id}]".format(
                t=title.name,
                s=title.season or 0,
                e=title.episode or 0,
                n=f" - {title.episode_name}" if title.episode_name else "",
                id=title.id,
            ))
        else:
            log.info("Getting tracks for {t}{y} [{id}]".format(
                t=title.name,
                y=f" ({title.year})" if title.year else "",
                id=title.id,
            ))

        try:
            new_tracks = service.get_tracks(title)
            # Propagate the service's chosen downloader onto any track that
            # didn't already opt in to one explicitly. Per-track overrides
            # set inside get_tracks() are preserved.
            service_downloader = getattr(service, "DOWNLOADER", "aria2c")
            for t in new_tracks:
                if getattr(t, "downloader", None) is None:
                    t.downloader = service_downloader
            title.tracks.add(new_tracks, warn_only=True)
            title.tracks.add(service.get_chapters(title))
        except requests.HTTPError as e:
            log.debug(traceback.format_exc())
            raise log.exit(f" - HTTP Error {e.response.status_code}: {e.response.reason}")

        title.tracks.sort_videos()
        title.tracks.sort_audios(by_language=alang)
        title.tracks.sort_subtitles(by_language=slang)
        title.tracks.sort_chapters()

        for track in title.tracks:
            if track.language == Language.get("none"):
                track.language = title.original_lang
            track.is_original_lang = is_close_match(track.language, [title.original_lang])

        # If original language is unknown (e.g. playlist lookup failed or service doesn't
        # expose it), infer it from the first audio track so that --alang orig doesn't
        # silently match nothing and error out.
        if not title.original_lang and title.tracks.audios:
            title.original_lang = title.tracks.audios[0].language
            log.debug(
                f" ! Original language unknown; inferred from first audio: {title.original_lang}"
            )
            for track in title.tracks:
                track.is_original_lang = is_close_match(track.language, [title.original_lang])

        if not list(title.tracks):
            log.error(" - No tracks returned!")
            continue

        if not selected:
            log.info("> All Tracks:")
            title.tracks.print()

        # Track Selection
        try:
            if quality and closest_resolution:
                available = [int(t.height) for t in title.tracks.videos]
                if not available:
                    log.error(" - No video tracks available")
                    continue
                if quality not in available:
                    closest = min(available, key=lambda x: abs(x - quality))
                    log.warning(f" - {quality}p not available, using closest: {closest}p")
                    quality = closest

            if range_ == "DV+HDR":
                title.tracks.select_videos_multi(["HDR10", "DV"], by_quality=quality, by_vbitrate=vbitrate)
            else:
                title.tracks.select_videos(
                    by_quality=quality, by_vbitrate=vbitrate, by_range=range_, one_only=True
                )

            title.tracks.select_audios(
                by_language=alang,
                by_bitrate=abitrate,
                with_descriptive=audio_description,
                by_codec=acodec,
                by_channels=audio_channels,
                max_audio_compatability=max_audio_compatibility,
            )
            forced_lang = alang if (match_forced and alang) else True
            title.tracks.select_subtitles(by_language=slang, with_forced=forced_lang)
        except ValueError as e:
            log.error(f" - {e}")
            continue

        # Exclusion Flags
        if no_video:
            title.tracks.videos.clear()
        if no_audio:
            title.tracks.audios.clear()
        if no_subs:
            title.tracks.subtitles.clear()
        if no_chapters:
            title.tracks.chapters.clear()

        if audio_only or subs_only or chapters_only:
            title.tracks.videos.clear()
            if audio_only and not subs_only:
                title.tracks.subtitles.clear()
            if audio_only and not chapters_only:
                title.tracks.chapters.clear()
            if subs_only and not audio_only:
                title.tracks.audios.clear()
            if subs_only and not chapters_only:
                title.tracks.chapters.clear()
            if chapters_only and not audio_only:
                title.tracks.audios.clear()
            if chapters_only and not subs_only:
                title.tracks.subtitles.clear()
            if not mux:
                no_mux = True

        log.info("> Selected Tracks:")
        title.tracks.print()

        if list_:
            continue

        if dry_run:
            ext = "mka" if audio_only else "mks" if subs_only else "mkv"
            log.info(f" > Predicted output: {title.filename}.{ext}")
            continue

        if _skip_existing:
            _check_dir = directories.downloads
            if title.type == Title.Types.TV:
                _check_dir = os.path.join(_check_dir, title.parse_filename(folder=True))
            if os.path.isdir(_check_dir):
                _existing = next(
                    (f for f in os.listdir(_check_dir)
                     if os.path.isfile(os.path.join(_check_dir, f)) and f.startswith(title.filename)),
                    None,
                )
                if _existing:
                    log.info(f" + Skipping — already exists: {_existing}")
                    continue

        # Per-Track Download/Decrypt
        skip_title = False
        all_content_keys: list = []

        # Services with DOWNLOAD_AUDIO_FIRST=True reverse track order so audio is
        # fetched before video (auth tokens can expire during large video downloads).
        track_order = (
            list(title.tracks)[::-1] if getattr(service, "DOWNLOAD_AUDIO_FIRST", False)
            else list(title.tracks)
        )

        for track in track_order:
            if not keys:
                log.info(f"Downloading: {track}")

            # Services with FORCE_ENCRYPT_VIDEO=True always treat video tracks
            # as encrypted even if the manifest does not mark them as such.
            if getattr(service, "FORCE_ENCRYPT_VIDEO", False) and "VID" in str(track):
                track.encrypted = True

            if track.encrypted:
                if not track.get_pssh(service.session):
                    raise log.exit(" - Failed to get PSSH")
                if track.psshPR:
                    log.info(f" + PSSH (PR): {track.psshPR}")
                if track.psshWV:
                    log.info(f" + PSSH (WV): {track.psshWV}")
                if not track.get_kid(service.session):
                    raise log.exit(" - Failed to get KID")
                log.info(f" + KID: {track.kid}")

            if not keys:
                proxy = (
                    next(iter(service.session.proxies.values()), None)
                    if track.needs_proxy else None
                )
                if isinstance(track, TextTrack):
                    time.sleep(5)  # Delay to avoid 403 ratelimit
                track.download(
                    directories.temp,
                    headers=service.session.headers,
                    proxy=proxy,
                    session=service.session,
                )
                log.info(" + Downloaded")

            if isinstance(track, VideoTrack) and track.needs_ccextractor_first and not no_subs:
                _run_ccextractor(service, title, track, no_subs)

            if track.encrypted:
                log.info("Decrypting...")
                try:
                    track_key, content_keys = _get_content_keys(
                        ctx, service, title, track,
                        no_cache=effective_no_cache,
                        cache=cache,
                    )
                except requests.HTTPError as e:
                    log.debug(traceback.format_exc())
                    raise log.exit(f" - HTTP {e.response.status_code}: {e.response.reason}")
                except Exception as e:
                    log.debug(traceback.format_exc())
                    raise log.exit(f" - Key retrieval failed: {e}")

                if track_key is None:
                    skip_title = True
                    break

                track.key = track_key
                if content_keys:
                    all_content_keys = content_keys

                if keys:
                    continue

                try:
                    _decrypt_track(track, service_name, all_content_keys,
                                   multi_key=getattr(service, "MULTI_KEY", False))
                except subprocess.CalledProcessError:
                    raise log.exit(" - Decryption failed")
                except RuntimeError as e:
                    raise log.exit(f" - {e}")
                log.info(" + Decrypted")

            if keys:
                continue

            # ISM Atmos (Extract EAC-3 JOC with ffmpeg 6.1.x)
            if (
                isinstance(track, AudioTrack)
                and track.descriptor == Track.Descriptor.ISM
                and getattr(track, "atmos", False)
            ):
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    raise log.exit(" - ffmpeg not found (needed for ISM Atmos extraction)")
                eac3 = os.path.splitext(track.locate())[0] + ".eac3"
                os.makedirs(directories.temp, exist_ok=True)
                try:
                    subprocess.run(
                        [ffmpeg, "-i", track.locate(), "-hide_banner", "-loglevel", "error", "-map", "0", "-c:a", "copy", eac3],
                        check=True,
                    )
                    track.swap(eac3)
                    log.info(" + Fixed ISM Atmos")
                except subprocess.CalledProcessError:
                    raise log.exit(" - ISM Atmos fixup failed")

            if track.needs_repack or (
                config.decrypter == "mp4decrypt" and isinstance(track, (VideoTrack, AudioTrack))
            ):
                log.info("Repackaging stream with ffmpeg (to fix malformed streams)")
                track.repackage()
                log.info(" + Repackaged")

            if isinstance(track, VideoTrack) and track.needs_ccextractor and not no_subs:
                _run_ccextractor(service, title, track, no_subs)

            if isinstance(track, TextTrack) and strip_sdh:
                track.strip_sdh()
                log.info(" + Stripped SDH to CC")

            if isinstance(track, TextTrack) and (
                getattr(config, "subtitles", None) or {}
            ).get("convert_to_srt", False):
                loc = track.locate()
                if loc and os.path.splitext(loc)[1].lower() not in (".srt",):
                    try:
                        import pysubs2
                        subs = pysubs2.load(loc)
                        new_loc = os.path.splitext(loc)[0] + ".srt"
                        subs.save(new_loc, format_="srt")
                        track.swap(new_loc)
                        log.info(" + Converted subtitle to SRT")
                    except Exception as e:
                        log.warning(f" ! SRT conversion failed: {e}")

        if skip_title:
            for t in title.tracks:
                t.delete()
            continue
        if keys:
            continue

        # DV+HDR Hybrid Creation
        if range_ == "DV+HDR":
            try:
                hybrid_path = title.tracks.make_hybrid()
                log.info(f" + DV+HDR hybrid created: {hybrid_path}")
            except Exception as e:
                log.warning(f" - Skipped DV+HDR hybrid: {e}")

        if not list(title.tracks) and not title.tracks.chapters:
            continue

        # Mux Individually
        if no_mux:
            out_dir = directories.downloads
            if title.type == Title.Types.TV:
                out_dir = os.path.join(out_dir, title.parse_filename(folder=True))
            os.makedirs(out_dir, exist_ok=True)

            if title.tracks.chapters:
                chap_loc = filenames.chapters.format(filename=title.filename)
                title.tracks.export_chapters(chap_loc)
                shutil.move(chap_loc, os.path.join(out_dir, os.path.basename(chap_loc)))

            for track in title.tracks:
                media_info = MediaInfo.parse(track.locate())
                fname = title.parse_filename(media_info=media_info)
                if isinstance(track, (AudioTrack, TextTrack)):
                    fname += f".{track.language}"
                ext = (
                    track.codec if isinstance(track, TextTrack)
                    else os.path.splitext(track.locate())[1][1:]
                )
                if isinstance(track, AudioTrack) and ext == "mp4":
                    ext = "m4a"
                track.move(os.path.join(out_dir, f"{fname}.{track.id}.{ext}"))
        else:
            log.info("Muxing tracks into an MKV container")
            muxed_loc, rc = title.tracks.mux(title.filename)
            if rc == 1:
                log.warning(" - mkvmerge had at least one warning, continuing...")
            elif rc >= 2:
                raise log.exit(" - Failed to mux tracks into MKV file")
            log.info(" + Muxed")

            for track in title.tracks:
                track.delete()
            if title.tracks.chapters:
                try:
                    os.unlink(filenames.chapters.format(filename=title.filename))
                except FileNotFoundError:
                    pass

            media_info = MediaInfo.parse(muxed_loc)
            out_dir = directories.downloads
            if title.type == Title.Types.TV:
                out_dir = os.path.join(
                    out_dir, title.parse_filename(media_info=media_info, folder=True)
                )
            os.makedirs(out_dir, exist_ok=True)
            ext = "mka" if audio_only else "mks" if subs_only else "mkv"
            shutil.move(
                muxed_loc,
                os.path.join(out_dir, f"{title.parse_filename(media_info=media_info)}.{ext}"),
            )

    log.info("Processed all titles!")


def load_services():
    for obj in services.__dict__.values():
        if callable(getattr(obj, "cli", None)):
            dl.add_command(obj.cli)


load_services()