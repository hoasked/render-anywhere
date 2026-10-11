import os
import urllib.request
import urllib.error
from pathlib import Path

# Read the secret from .dev.vars without printing it.
secret = None
for line in Path(".dev.vars").read_text().splitlines():
    if line.strip().startswith("RELAY_SECRET="):
        secret = line.split("=", 1)[1].strip().strip('"').strip("'")
        secret = secret.encode("utf-8").decode("ascii")
        break

if not secret:
    raise SystemExit("RELAY_SECRET was not found in .dev.vars")

request = urllib.request.Request(
    "http://127.0.0.1:8787/?device_id=my-render-pc",
    headers={"Authorization": f"Bearer {secret}"},
)

try:
    with urllib.request.urlopen(request) as response:
        print("Status:", response.status)
        print("Response:", response.read().decode())
except urllib.error.HTTPError as error:
    print("Status:", error.code)
    print("Response:", error.read().decode())

print("\nTesting request without authentication...")

request = urllib.request.Request(
    "http://127.0.0.1:8787/?device_id=my-render-pc"
)

try:
    with urllib.request.urlopen(request) as response:
        print("Unexpected status:", response.status)
        print("WARNING: Unauthorized request was accepted!")
except urllib.error.HTTPError as error:
    print("Status:", error.code)
    print("Blocked:", error.code == 401)
    print("Response:", error.read().decode())

