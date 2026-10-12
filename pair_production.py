
import json
import secrets
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://cloud.t0257354.workers.dev"
DEVICE_ID = "my-render-pc"
ROOT = Path(__file__).resolve().parent


def read_secret():
    path = ROOT / ".dev.vars"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("RELAY_SECRET="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("RELAY_SECRET not found in .dev.vars")


def call(method, path, token=None, body=None):
    headers = {"User-Agent": "RenderAnywhere-Diagnostic/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        BASE_URL + path, data=data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            result = {"error": text}
        return exc.code, result


def require(status, expected, step, result):
    if status != expected:
        raise RuntimeError(f"{step} failed: HTTP {status}: {result}")
    print("PASS:", step)


def main():
    secret = read_secret()
    query = f"?device_id={DEVICE_ID}"

    status, session = call(
        "POST", "/pairing/session" + query, token=secret, body={}
    )
    require(status, 201, "Create production pairing session", session)

    session_query = query + "&session_id=" + session["session_id"]
    phone_credential = secrets.token_hex(32)

    status, result = call(
        "POST", "/pairing/request" + session_query,
        body={
            "token": session["token"],
            "phone_credential": phone_credential,
        },
    )
    require(status, 202, "Submit phone pairing request", result)

    status, result = call(
        "GET", "/pairing/status" + session_query, token=secret
    )
    require(status, 200, "Check pairing request", result)
    if result.get("status") != "requested":
        raise RuntimeError("Pairing request is not awaiting approval.")

    status, result = call(
        "POST", "/pairing/approve" + session_query,
        token=secret, body={}
    )
    require(status, 200, "Approve phone pairing", result)
    if result.get("status") != "approved":
        raise RuntimeError("The Worker did not confirm approval.")

    status, result = call(
        "POST", "/pairing/complete" + session_query,
        token=phone_credential, body={}
    )
    require(status, 200, "Complete phone pairing", result)
    if result.get("status") != "completed":
        raise RuntimeError("The Worker did not confirm completion.")

    credential_path = ROOT / "phone_credential.txt"
    temp_path = ROOT / "phone_credential.txt.tmp"
    temp_path.write_text(phone_credential, encoding="utf-8")
    temp_path.replace(credential_path)

    print("\nPairing completed successfully.")
    print("The new phone credential was saved locally.")
    print("Credential contents will not be displayed.")


if __name__ == "__main__":
    main()
