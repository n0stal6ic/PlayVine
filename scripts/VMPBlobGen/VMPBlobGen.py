import os
import sys
from hashlib import sha512
from playvine.utils.widevine.protos.widevine_pb2 import FileHashes
from playvine.utils.widevine.vmp import WidevineSignatureReader

"""
Script that generates a VMP blob for chromecdm

- Android doesn't require (or use!) a VMP blob (the oemcrypto hardware backs it and HDCP controls the path)
- Chrome and WidevineCDM both have signature files. The widevinecdm.dll and chrome.exe sign both the signature files,
  then sign with the private key and inject to the license request in field 7, but you need a server cert to encrypt
  the challenge otherwise.
"""

WIN32_FILES = [
    "chrome.exe",
    "chrome.dll",
    "chrome_child.dll",
    "widevinecdmadapter.dll",
    "widevinecdm.dll"
]


def sha512file(filename):
    """Compute SHA-512 digest of file."""
    sha = sha512()
    with open(filename, "rb") as fd:
        for b in iter(lambda: fd.read(0x10000), b''):
            sha.update(b)
    return sha.digest()


def build_vmp_field(filenames):
    """
    Create and fill out a FileHashes object.

    `filenames` is an array of pairs of filenames like (file, file_signature)
    such as ("module.dll", "module.dll.sig"). This does not validate the signature
    against the codesign root CA, or even the sha512 hash against the current signature+signer
    """
    file_hashes = FileHashes()

    for basename, file, sig in filenames:
        signature = WidevineSignatureReader.from_file(sig)
        s = file_hashes.signatures.add()
        s.filename = basename
        s.test_signing = False
        s.SHA512Hash = sha512file(file)
        s.main_exe = signature.mainexe
        s.signature = signature.signature

    file_hashes.signer = signature.signer
    return file_hashes.SerializeToString()


def get_files_with_signatures(path, required_files=None, random_order=False, sig_ext="sig"):
    """
    Use on a chrome directory (A given version).
    random_order would put any files it found in the directory with signatures,
    It's not the right way to do it and the browser does not do this.
    This function can still fail (generate wrong output) in subtle ways if
    the Chrome directory has copies of the exe/sigs, 
    especially if those copies are modified in some way.
    """
    if not required_files:
        required_files = WIN32_FILES

    all_files = []
    sig_files = []
    for dir_path, _, filenames in os.walk(path):
        for filename in filenames:
            full_path = os.path.join(dir_path, filename)
            all_files.append(full_path)
            if filename.endswith(sig_ext):
                sig_files.append(full_path)

    base_names = []
    for path in sig_files:
        orig_path = os.path.splitext(path)[0]
        if orig_path not in all_files:
            print("signature file {} lacks original file {}".format(path, orig_path))
        base_names.append(path.name)

    if not set(base_names).issuperset(set(required_files)):
        raise ValueError("Missing a binary/signature pair from {}".format(required_files))

    files_to_hash = []
    if random_order:
        for path in sig_files:
            orig_path = os.path.splitext(path)[0]
            files_to_hash.append((os.path.basename(orig_path), orig_path, path))
    else:
        for basename in required_files:
            found_file = False
            for path in sig_files:
                orig_path = os.path.splitext(path)[0]
                if orig_path.endswith(basename):
                    files_to_hash.append((basename, orig_path, path))
                    found_file = True
                    break
            if not found_file:
                raise Exception("Failed to locate a file signature pair for {}".format(basename))

    return files_to_hash


def make_vmp_buff(browser_dir, file_msg_out):
    with open(file_msg_out, "wb") as fd:
        fd.write(build_vmp_field(get_files_with_signatures(browser_dir)))


if len(sys.argv) < 3:
    print("Usage: {} BrowserPathWithVersion OutputPBMessage.bin".format(sys.argv[0]))
else:
    make_vmp_buff(sys.argv[1], sys.argv[2])