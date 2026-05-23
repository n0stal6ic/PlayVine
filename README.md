<div align="center">
  <h1>
    <img src="./assets/icon.png" width="80" alt="" align="absmiddle" />
    &nbsp;PlayVine
  </h1>

  <p><em>A tool for archiving content from streaming services</em></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10%20–%203.12-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.10-3.12" />
    <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square" alt="Platform" />
    <img src="https://img.shields.io/badge/DRM-Widevine-ff6b35?style=flat-square" alt="Widevine" />
    <img src="https://img.shields.io/badge/DRM-PlayReady-0078d4?style=flat-square" alt="PlayReady" />
  </p>
</div>

## PlayVine?

PlayVine is a command-line tool for downloading and decrypting content from streaming platforms with support for Widevine and PlayReady DRM handling. It ships as a clean framework with no pre-installed services. 

## Features

- **Widevine and PlayReady** - Both DRM systems supported, auto-detected from your device file
- **DASH, HLS, and ISM** - Built-in manifest parsers for MPD, M3U8, and ISM formats
- **Multi-key content** - Handles multi-key CENC out of the box
- **Key vault** - Caches and reuses decryption keys across sessions via local or remote vaults
- **Service plugins** - Drop a `.py` file into `playvine/services/` and it is ready to use,
- **Track selection** - Fine control over video quality, codecs, audio languages, subtitles, and dynamic range
- **HDR and Dolby Vision** - Supports SDR, HDR10, HLG, DV, and DV+HDR hybrid downloads
- **Fast downloads** - Numerous binary integration for multi-connection segment downloading
- **Auto muxing** - Downloaded tracks are automatically muxed into a clean MKV
- **Remote CDM** - Connect to a remote Widevine or PlayReady API instead of a local device file

---

## Requirements

- **Python 3.10 to 3.12**
- [uv](https://docs.astral.sh/uv/) Python package manager for a virtual environment
- A Widevine (`.wvd`) or PlayReady (`.prd`) device file
- Custom built service script for streaming platforms
- External binaries placed in `binaries/` or available on your system PATH:

| Binary | Purpose | Required |
|--------|---------|----------|
| `ffmpeg` / `ffprobe` | Audio and video processing | Yes |
| `mkvmerge` | MKV container muxing | Yes |
| `mp4decrypt` or `shaka-packager` | DRM decryption | Yes |
| `N_m3u8DL-RE` | HLS and DASH segment downloading | Recommended |
| `aria2c` | Multi-connection downloading | Optional |
| `ccextractor` | EIA-608 caption extraction | Optional |

---

## Installation

### Windows
Run the install batch file to create the virtual environment and install dependencies:

```bat
install.bat
```

Run the virtual environment batch file to open an activated shell afterwards:

```bat
venv.bat
```

### Other Platform

```bash
pip install uv
uv venv
uv sync
```
Then activate:

```bash
# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```
You may skip activation and prefix commands with `uv run`:

```bash
uv run pv dl MyService https://...
```
For additional help use the `--help` flag:

```bash
uv run pv dl --help
```

---

## Configuration

The main configuration is at `playvine/playvine.yml`. Copy the default from `playvine/config/playvine.yml` as a starting point:

```yaml
# Decrypter to use
decrypter: 'packager'

# Release group tag
tag: 'NOGRP'

# CDM device filename
cdm:
  default: 'your_device_name'

# Service credentials
credentials:
  MyService:
    default: 'username:password'

# Key vaults
key_vaults:
  - type: 'local'
    name: 'Local'
    path: '{data_dir}/key_store.db'

# Proxies (country code to URI mapping, used with --proxy US)
proxies:
  US: 'socks5://user:pass@host:port'
```

Per-service proxies can also be set directly in the service YAML config. Place the file at `playvine/config/Services/ServiceName.yml`:

```yaml
proxy: 'socks5://user:pass@host:port'
```

This proxy is used automatically for that service without needing `--proxy` on the command line. The CLI `--proxy` flag always takes priority, and `--no-proxy` disables all proxy use.

### CDM Devices

Place your device files in `playvine/devices/`:

```
playvine/devices/
├── my_widevine_device.wvd
└── my_playready_device.prd
```

Set `cdm.default: my_widevine_device` in the config (no file extension needed).

### Cookies

Export cookies in netscape format and save them here:

```
playvine/Cookies/
└── ServiceName/
    └── default.txt
```

---

## Adding Services

Add a `.py` file into `playvine/services/` and PlayVine picks it up on the next run with no imports or changes needed.

Your service subclasses `BaseService` and declares its aliases:

```python
from playvine.services.BaseService import BaseService
import click

class MyService(BaseService):
    ALIASES = ["MSV", "myservice"]
    TITLE_RE = r"https?://myservice\.com/(?P<id>[a-z0-9]+)"

    @staticmethod
    @click.command(name="MyService", short_help="https://myservice.com")
    @click.argument("title")
    @click.pass_context
    def cli(ctx, **kwargs):
        return MyService(ctx, **kwargs)

    def get_titles(self): ...
    def get_tracks(self, title): ...
    def get_chapters(self, title): return []
    def certificate(self, **kwargs): return None
    def license(self, challenge, **kwargs): ...
```

---

## Usage

```
pv [--debug] dl [OPTIONS] SERVICE TITLE
```

Both `pv` and `playvine` are valid command names. The `--debug` flag goes before `dl`.

### Options

| Flag | Description |
|------|-------------|
| `-q 1080` | Download in 1080p. Also accepts `720`, `2160`, `4K`, `SD` |
| `-cr` | Use closest available resolution if an exact match is not found |
| `-v H265` | Video codec. Options: `H264`, `H265`, `VP9`, `AV1` |
| `-a EC3` | Audio codec preference. Options: `AAC`, `AC3`, `EC3` |
| `-aa` | Prefer Dolby Atmos audio |
| `-r DV` | Dynamic range. Options: `SDR`, `HDR10`, `HLG`, `DV`, `DV+HDR` |
| `-al orig` | Original language audio only (default) |
| `-al en` | English audio only |
| `-al en,fr` | Multiple languages |
| `-al all` | All available audio tracks |
| `-sl all` | All subtitle tracks (default) |
| `-sl en` | Specific subtitle language |
| `-ns` | Skip subtitles |
| `-na` | Skip audio tracks |
| `-nv` | Skip video track |
| `-A` | Audio only |
| `-S` | Subtitles only |
| `-w S01-S03` | Season range filter |
| `-w S02E01-S02E05` | Episode range filter |
| `-le` | Latest episode only |
| `--list` | List all available tracks without downloading |
| `--dry-run` | Preview output filename and selected tracks without downloading |
| `-se` | Skip titles that already exist in the download directory |
| `--keys` | Print decryption keys only, no download |
| `--no-mux` | Keep individual track files, skip MKV muxing |
| `--no-proxy` | Disable all proxy use |
| `--cdm name` | Override the CDM device for this run |
| `--cache` | Use key vault only, skip CDM if key is not cached |
| `--no-cache` | Use CDM only, skip vault lookup |
| `-ss` | Strip SDH formatting and convert to clean CC subtitles |
| `-mf` | Forced subtitles matching audio language only |

### Examples

```bash
# Download a movie at best available quality
pv dl MyService https://myservice.com/movie/<movie_id>

# 4K with Dolby Vision and Atmos
pv dl MyService <movie_id> -q 2160 -r DV -aa

# Full series, Seasons 1 through 3, 1080p, English audio and all subs
pv dl MyService <movie_id> -q 1080 -w S01-S03 -al en -sl all

# List available tracks without downloading
pv dl MyService <movie_id> -w S01E01 --list

# Print decryption keys only
pv dl MyService <movie_id> --keys

# Run with debug logging
pv --debug dl MyService <movie_id>
```

---

## Project Structure

```
PlayVine/
├── playvine/
│   ├── commands/
│   │   └── dl.py               - download command
│   ├── config/
│   │   ├── playvine.yml        - default config
│   │   └── Services/           - per-service YAML configs
│   ├── cookies/                - place netscape cookies here
│   ├── devices/                - place .wvd and .prd files here
│   ├── objects/                - Title, Track, and Vault data models
│   ├── parsers/                - DASH/MPD, HLS/M3U8, and ISM parsers
│   ├── services/               - add service .py files here
│   │   └── BaseService.py      - base class all services extend
│   ├── utils/                  - shared utilities
│   ├── vendor/                 - vendored third-party libraries
│   └── playvine.py             - CLI entry point
├── scripts/                    - embedded libraries (pywidevine, pyplayready, etc.)
├── binaries/                   - add ffmpeg, mkvmerge, mp4decrypt, etc. here
├── assets/                     - icons and branding
├── install.bat                 - Windows quick-install script
├── venv.bat                    - Windows virtual environment activation shortcut
└── pyproject.toml              - project and dependency config
```

---

## Information

1. This program is intended for personal archival and educational use with content you have the legal right to access.
2. This program does not facilitate or encourage the circumvention of copyright protections.
3. This program does not include or distribute device files or service scripts.
5. This program is made free and open source.

---