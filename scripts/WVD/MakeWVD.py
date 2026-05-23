import argparse
import json
import os
import re
import sys
from playvine.utils.widevine.device import LocalDevice

"""
Code to convert common folder/file structure to a WVD.
"""

parser = argparse.ArgumentParser()
parser.add_argument("dirs", metavar="DIR", nargs="+", help="Directory containing device files")
args = parser.parse_args()

configs = []
for d in args.dirs:
    for root, dirs, files in os.walk(d):
        for f in files:
            if f == "wv.json":
                configs.append(os.path.join(root, f))

if not configs:
    print("No wv.json file found.")
    sys.exit(1)

for f in configs:
    d = os.path.dirname(f)

    print(f"Generating WVD structure file for {os.path.abspath(d)}...")

    with open(f, encoding="utf-8") as fd:
        config = json.load(fd)

    device = LocalDevice.from_dir(d)

    name = re.sub(r"_lvl\d$", "", config["name"])
    out_path = f"{name}_l{device.security_level}_{device.system_id}.wvd"

    device.dump(out_path)

    print(device)

    print(f"Done, saved to: {os.path.abspath(out_path)}")
    print()