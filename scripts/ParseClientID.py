import argparse
from playvine.utils.widevine.device import LocalDevice
from playvine.utils.widevine.protos.widevine_pb2 import ClientIdentification

parser = argparse.ArgumentParser(
    "Client Identification Parser",
    description="Read a client_id blob."
)
parser.add_argument(
    "input",
    help="Path to client_id blob bin or WVD file",
)
args = parser.parse_args()

client_id = ClientIdentification()
is_wvd = args.input.lower().endswith(".wvd")

with open(args.input, "rb") as fd:
    data = fd.read()

if is_wvd:
    client_id = LocalDevice.load(data).client_id
else:
    client_id.ParseFromString(data)

print(client_id)