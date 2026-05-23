import xmltodict
import asyncio
import base64
import json
import math
import os
import re
import urllib.parse
import uuid
from copy import copy
from hashlib import md5
import requests
from langcodes import Language
from langcodes.tag_parser import LanguageTagError
from playvine import config
from playvine.objects import AudioTrack, TextTrack, Track, Tracks, VideoTrack
from playvine.utils.io import aria2c
from playvine.vendor.pymp4.parser import Box

# A stream from ISM is always in fragments
# Example fragment URL
# https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism.smoothstreaming/QualityLevels(128003)/Fragments(aac_UND_2_128=0)
# based on https://github.com/SASUKE-DUCK/pywks/blob/dba8a83a0722221bd8d3e53d624b91050b46cfde/cdm/wks.py#L722
def parse(*, url=None, data=None, source, session=None, downloader=None):
	"""
	Convert an Smooth Streaming ISM (IIS Smooth Streaming Manifest) document to a Tracks object
	with video, audio and subtitle track objects where available.

	:param url: URL of the ISM document.
	:param data: The ISM document as a string.
	:param source: Source tag for the returned tracks.
	:param session: Used for any remote calls, e.g. getting the MPD document from an URL.
		Can be useful for setting custom headers, proxies, etc.
	:param downloader: Downloader to use. Accepted values are None (use requests to download)
		and aria2c.

	Don't forget to manually handle the addition of any needed or extra information or values
	like `encrypted`, `pssh`, `hdr10`, `dv`, etc. Essentially anything that is per-service
	should be looked at. Some of these values like `pssh` will be attempted to be set automatically
	if possible but if you definitely have the values in the service, then set them.

	Examples:
		url = "https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism.smoothstreaming/manifest"
		session = requests.Session(headers={"X-Example": "foo"})
		tracks = Tracks.from_ism(url=url, data=session.get(url).text, source="MICROSOFT")
	"""
	base_url = (url.rsplit('/', 1)[0] + '/') if url else ""

	if not data:
		if not url:
			raise ValueError("Neither a URL nor a document was provided to Tracks.from_ism")
		if downloader is None:
			data = (session or requests).get(url, verify=False).text
		elif downloader == "aria2c":
			out = os.path.join(config.directories.temp, url.split("/")[-1])
			asyncio.run(aria2c(url, out))
			with open(out, encoding="utf-8") as fd:
				data = fd.read()
			try:
				os.unlink(out)
			except FileNotFoundError:
				pass
		else:
			raise ValueError(f"Unsupported downloader: {downloader}")

	ism = xmltodict.parse(data)
	if not ism["SmoothStreamingMedia"]:
		raise ValueError("Non-ISM document provided to Tracks.from_ism")

	# Protection / Encryption info (May be absent for clear streams)
	encrypted = False
	pssh = None
	kid = None
	protection = ism['SmoothStreamingMedia'].get('Protection')
	if protection:
		ph = protection.get('ProtectionHeader') if isinstance(protection, dict) else None
		if ph:
			sys_id = (ph.get('@SystemID', '') or '').replace('-', '').upper()
			if sys_id in ('9A04F07998404286AB92E65BE0885F95', 'EDEF8BA979D64ACEA3C827DCD51D21ED'):
				encrypted = True
			pssh = ph.get('#text')
			if pssh:
				try:
					pr_dec = base64.b64decode(pssh).decode('utf16')
					pr_dec = pr_dec[pr_dec.index('<'):]
					pr_xml = xmltodict.parse(pr_dec)
					kid_b64 = pr_xml['WRMHEADER']['DATA']['KID']
					kid = uuid.UUID(base64.b64decode(kid_b64).hex()).bytes_le.hex()
				except Exception:
					pass

	stream_indices = ism['SmoothStreamingMedia']['StreamIndex']

	assert int(ism['SmoothStreamingMedia'].get('@Duration'))
	assert int(ism['SmoothStreamingMedia'].get('@TimeScale'))

	tracks = []

	for stream_info in (stream_indices if isinstance(stream_indices, list) else [stream_indices]):
		type_info = stream_info['@Type']

		quality_levels = stream_info.get('QualityLevel', [])
		if not isinstance(quality_levels, list):
			quality_levels = [quality_levels]

		# Fragment start-times from <c> elements (cumulative if @n absent)
		c_elements = stream_info.get('c') or stream_info.get('C') or []
		if isinstance(c_elements, dict):
			c_elements = [c_elements]

		for quality_level in quality_levels:
			fourCC = quality_level.get('@FourCC', '') or ''
			bitrate = int(quality_level.get('@Bitrate') or 0)

			if type_info == 'video':
				width = int(quality_level.get('@MaxWidth') or 0)
				height = int(quality_level.get('@MaxHeight') or 0)
			else:
				width = 0
				height = 0

			privateData = (quality_level.get('@CodecPrivateData', '') or '').strip() or None

			if fourCC.upper() in ("H264", "X264", "DAVC", "AVC1"):
				try:
					result = re.compile(r"00000001\d7([0-9a-fA-F]{6})").match(privateData)[1]
					codec = f"avc1.{result}"
				except Exception:
					codec = "avc1.4D401E"
			elif fourCC[:3].upper() == "AAC":
				mpProfile = 2
				if fourCC.upper() == "AACH":
					mpProfile = 5
				elif privateData:
					mpProfile = (int(privateData[:2], 16) & 0xF8) >> 3
					if mpProfile == 0:
						mpProfile = 2
				codec = f"mp4a.40.{mpProfile}"
			else:
				codec = fourCC

			lang_raw = (stream_info.get('@Language', '') or '').strip()
			try:
				track_lang = Language.get(lang_raw.split("-")[0])
				lang = lang_raw.split("-")[0]
			except Exception:
				track_lang = Language.get("und")
				lang = "und"

			audio_id = stream_info.get('@AudioTrackId', '') or ''

			track_id = "{codec}-{lang}-{bitrate}-{extra}".format(
				codec=codec,
				lang=track_lang,
				bitrate=bitrate or 0,
				extra=audio_id + (quality_level.get("@Index") or "") + (privateData or ""),
			)
			track_id = md5(track_id.encode()).hexdigest()

			# Build proper per-fragment URLs from <c> elements; fall back to manifest URL
			url_tpl = (stream_info.get("@Url") or "").replace("{bitrate}", str(bitrate))
			fragment_urls = []
			if c_elements and base_url and url_tpl:
				t = 0
				for c in c_elements:
					if "@n" in c:
						t = int(c["@n"])
					d = int(c.get("@d") or 0)
					fragment_urls.append(base_url + url_tpl.replace("{start time}", str(t)))
					t += d
			track_url = fragment_urls if fragment_urls else (url or "")

			if type_info == 'video':
				tracks.append(VideoTrack(
					id_=track_id,
					source=source,
					original_url=url,
					url=track_url,
					codec=(codec or "").split(".")[0],
					language=track_lang,
					bitrate=bitrate,
					width=width,
					height=height,
					fps=None,
					hdr10=bool(codec and codec[0:4] in ("hvc1", "hev1")),
					hlg=False,
					dv=bool(codec and codec[0:4] in ("dvhe", "dvh1")),
					descriptor=Track.Descriptor.ISM,
					needs_repack=True,
					encrypted=encrypted,
					psshPR=pssh,
					kid=kid,
					extra=(dict(quality_level), dict(stream_info), lang,)
				))
			elif type_info == 'audio':
				atmos = (
					str(quality_level.get('@HasAtmos', '')).lower() == "true"
					or "ATM" in (stream_info.get('@Name', '') or '')
				)
				tracks.append(AudioTrack(
					id_=track_id,
					source=source,
					url=track_url,
					codec="E-AC3" if codec == "EC-3" else (codec or "").split(".")[0],
					language=lang,
					bitrate=bitrate,
					channels=quality_level.get('@Channels'),
					atmos=atmos,
					descriptor=Track.Descriptor.ISM,
					needs_repack=True,
					encrypted=encrypted,
					psshPR=pssh,
					kid=kid,
					extra=(dict(quality_level), dict(stream_info), lang,)
				))
			elif type_info == 'text':
				text_codec = (fourCC.lower() if fourCC else None) or 'ttml'
				tracks.append(TextTrack(
					id_=track_id,
					source=source,
					url=track_url,
					codec=text_codec,
					language=lang,
					descriptor=Track.Descriptor.ISM,
					needs_repack=False,
					encrypted=encrypted,
					psshPR=pssh,
					kid=kid,
					extra=(dict(quality_level), dict(stream_info), lang,)
				))

	return tracks