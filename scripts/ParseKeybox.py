import argparse
from playvine.utils.widevine.keybox import Keybox

parser = argparse.ArgumentParser(
    "Keybox Parser",
    description="Read a keybox"
)
parser.add_argument(
    "-k", "--keybox",
    help="Keybox Path",
    required=True)
args = parser.parse_args()

keybox = Keybox.load(args.keybox)
print(repr(keybox))