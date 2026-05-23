import warnings
warnings.filterwarnings("ignore", message="urllib3", category=Warning)
import logging
import os
import sys
from datetime import datetime
import traceback
import click
from playvine.config import directories, filenames
from playvine.commands.dl import dl
from playvine.utils.console import install_handler, show_banner


@click.command(context_settings=dict(
    allow_extra_args=True,
    ignore_unknown_options=True,
    max_content_width=116,
))
@click.option("--debug", is_flag=True, default=False,
              help="Enable DEBUG level logs on the console.")
def main(debug):
    """
    PlayVine is a convenient command-line program to
    download videos from Widevine and PlayReady DRM-protected platforms.
    """
    LOG_FORMAT = "{asctime} [{levelname[0]}] {name} : {message}"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    LOG_STYLE = "{"

    def log_exit(self, msg, *args, **kwargs):
        self.critical(msg, *args, **kwargs)
        sys.exit(1)

    logging.Logger.exit = log_exit

    os.makedirs(directories.logs, exist_ok=True)
    # File handler keeps the full timestamped format so disk logs remain
    # easy to grep / diff across runs.
    logging.basicConfig(
        level=logging.DEBUG,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        style=LOG_STYLE,
        handlers=[logging.FileHandler(
            os.path.join(directories.logs, filenames.log.format(time=datetime.now().strftime("%Y%m%d-%H%M%S"))),
            encoding='utf-8',
        )]
    )

    # Console handler swaps coloredlogs for the PlayVine rich-based look:
    # glyph-prefixed lines, no timestamps, vine-green accent.
    install_handler(level=logging.DEBUG if debug else logging.INFO)

    # Startup banner - replaces the seven sequential log.info() path lines.
    show_banner({
        "Config":    filenames.user_root_config,
        "Cookies":   directories.cookies,
        "Devices":   directories.devices,
        "Cache":     directories.cache,
        "Logs":      directories.logs,
        "Temp":      directories.temp,
        "Downloads": directories.downloads,
    })

    log = logging.getLogger("playvine")
    log.debug(sys.argv)

    from playvine.config import config as _cfg

    _cdm_default = (_cfg.cdm or {}).get("default", "")
    if not _cdm_default or _cdm_default == "your_device_name":
        log.warning(" ! No CDM configured. Set cdm.default in playvine/playvine.yml to a device.")
    else:
        _dev_dir = directories.devices
        _found_device = (
            os.path.isfile(os.path.join(_dev_dir, f"{_cdm_default}.wvd"))
            or os.path.isfile(os.path.join(_dev_dir, f"{_cdm_default}.prd"))
            or os.path.isdir(os.path.join(_dev_dir, _cdm_default))
        )
        if not _found_device:
            log.warning(
                f" ! CDM device '{_cdm_default}' not found in {_dev_dir}. "
                "Check cdm.default in playvine/playvine.yml."
            )

    _decrypter = (_cfg.decrypter or "").strip()
    if not _decrypter:
        log.warning(" ! No decrypter configured. Set decrypter in playvine/playvine.yml.")
    elif _decrypter not in ("packager", "mp4decrypt"):
        log.warning(f" ! Unknown decrypter '{_decrypter}'.")

    if not (_cfg.key_vaults or []):
        log.warning(" ! No key vaults configured. Decryption keys will not be cached between sessions.")

    os.environ['PATH'] = os.path.abspath('./binaries') + os.pathsep + os.environ.get('PATH', '')

    try:
        sys.set_int_max_str_digits(10000)
    except AttributeError:
        pass

    for _i, _arg in enumerate(sys.argv[1:], 1):
        if _arg.lower() == "dl":
            sys.argv.pop(_i)
            break

    try:
        dl()
    except Exception:
        log.error("\n" + traceback.format_exc())


if __name__ == "__main__":
    main()