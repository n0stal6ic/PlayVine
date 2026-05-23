import argparse
import base64
import json
import os
from playvine.utils.widevine.device import LocalDevice

"""
Code to convert common folder/file structure to a playvine WVD.
"""

parser = argparse.ArgumentParser(
    "JsonWVDtoStructWVD",
    description="Read CDM data from old WVD and convert to new structure."
)
parser.add_argument(
    "-i", "--input",
    help="Path to WVD JSON file",
    required=False)
parser.add_argument(
    "-d", "--dir",
    help="Path to MULTIPLE WVD JSON files",
    required=False)
args = parser.parse_args()

files = []
if args.dir:
    files.extend(os.listdir(args.dir))
elif args.input:
    files.append(args.input)

for file in files:
    if not file.lower().endswith(".wvd") or os.path.splitext(file)[0].endswith(".struct"):
        continue

    if not os.path.isfile(file):
        raise ValueError("Not a file or doesn't exist.")

    print(f"Generating WVD structure file for {file}.")

    with open(file, encoding="utf-8") as fd:
        wvd_json = json.load(fd)

    device = LocalDevice(
        type=LocalDevice.Types[wvd_json["device_type"].upper()],
        security_level=wvd_json["security_level"],
        flags={
            "send_key_control_nonce": wvd_json["send_key_control_nonce"]
        },
        private_key=base64.b64decode(wvd_json["device_private_key"]),
        client_id=base64.b64decode(wvd_json["device_client_id_blob"]),
        vmp=base64.b64decode(wvd_json["device_vmp_blob"]) if wvd_json.get("device_vmp_blob") else None
    )

    out = os.path.join(os.path.dirname(file), "structs", os.path.basename(file))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    device.dump(out)

    print(device)
    print(f"Done: {file}")

print("Done")