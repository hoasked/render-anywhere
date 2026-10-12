import urllib.error
import urllib.request
import json
import secrets
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://cloud.t0257354.workers.dev"
DEVICE_ID = "my-render-pc"


def read_secret():
	path = Path(__file__).resolve().parent / ".dev.vars"

	for line in path.read_text(encoding="utf-8").splitlines():
		if line.strip().startswith("RELAY_SECRET="):
			return line.split("=", 1)[1].strip().strip('"').strip("'")

	raise RuntimeError("RELAY_SECRET was not found in .dev.vars")


def call(method, path, token=None, body=None):
	headers = {}

	if token:
		headers["Authorization"] = f"Bearer {token}"

	data = None
	if body is not None:
		data = json.dumps(body).encode("utf-8")
		headers["Content-Type"] = "application/json"

	request = urllib.request.Request(
		BASE_URL + path,
		data=data,
		headers=headers,
		method=method,
	)

	try:
		with urllib.request.urlopen(request, timeout=10) as response:
			text = response.read().decode("utf-8")
			return response.status, json.loads(text) if text else {}
	except urllib.error.HTTPError as error:
		text = error.read().decode("utf-8")
		try:
			result = json.loads(text)
		except json.JSONDecodeError:
			result = {"error": text}
		return error.code, result


def check(condition, message):
	if not condition:
		raise RuntimeError("FAILED: " + message)
	print("PASS:", message)


def main():
	secret = read_secret()
	base = f"?device_id={DEVICE_ID}"
	credential_path = Path(__file__).resolve().parent / "phone_credential.txt"
	previous_phone_credential = None

	if credential_path.exists():
		previous_phone_credential = credential_path.read_text(
			encoding="utf-8"
		).strip()

	print("Testing pairing flow locally...")

	status, _ = call("POST", "/pairing/session" + base)
	check(status == 401, "Unauthenticated session creation is blocked")

	status, session = call(
		"POST",
		"/pairing/session" + base,
		token=secret,
		body={},
	)
	check(status == 201, "Authenticated PC creates a pairing session")

	session_id = session["session_id"]
	qr_token = session["token"]
	session_query = base + "&session_id=" + session_id

	phone_credential = secrets.token_hex(32)
	Path("phone_credential.txt").write_text(
		phone_credential,
		encoding="utf-8",
	)

	status, result = call(
		"POST",
		"/pairing/request" + session_query,
		body={
			"token": qr_token,
			"phone_credential": phone_credential,
		},
	)

	print("Pairing request HTTP status:", status)
	print("Pairing request response:", result)

	check(status == 202, "Phone claims the temporary QR token")

	status, result = call(
		"GET",
		"/pairing/status" + session_query,
		token=secret,
	)
	check(
		status == 200 and result.get("status") == "requested",
		"PC sees the pending pairing request",
	)

	status, result = call(
		"POST",
		"/pairing/approve" + session_query,
		token=secret,
		body={},
	)
	check(
		status == 200 and result.get("status") == "approved",
		"PC approves the phone",
	)

	status, result = call(
		"POST",
		"/pairing/complete" + session_query,
		token=phone_credential,
		body={},
	)

	print("Completion HTTP status:", status)
	print("Completion response:", result)

	check(
		status == 200 and result.get("status") == "completed",
		"Phone completes pairing",
	)

	status, result = call(
		"GET",
		"/pairing/status" + session_query,
		token=phone_credential,
	)
	check(
		status == 200 and result.get("status") == "completed",
		"Paired phone can check its session status",
	)

	print("\nTesting incorrect phone credential...")

	wrong_credential = secrets.token_hex(32)

	status, _ = call(
		"GET",
		"/pairing/status" + session_query,
		token=wrong_credential,
	)

	check(
		status == 401,
		"Phone with incorrect credential is rejected",
	)

	print("\nTesting incorrect WebSocket credential...")

	wrong_ws_request = urllib.request.Request(
		f"http://127.0.0.1:8787/?role=phone&device_id={DEVICE_ID}",
		headers={
			"Authorization": f"Bearer {wrong_credential}",
			"Upgrade": "websocket",
			"Connection": "Upgrade",
			"Sec-WebSocket-Version": "13",
			"Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
		},
	)

	try:
		with urllib.request.urlopen(wrong_ws_request, timeout=5) as response:
			ws_status = response.status
	except urllib.error.HTTPError as error:
		ws_status = error.code

	check(
		ws_status == 401,
		"WebSocket connection with incorrect credential is rejected",
	)

	print("\nTesting phone credential against another device...")

	other_device_request = urllib.request.Request(
		"http://127.0.0.1:8787/"
		"?role=phone&device_id=isolation-test-pc",
		headers={
			"Authorization": f"Bearer {phone_credential}",
			"Upgrade": "websocket",
			"Connection": "Upgrade",
			"Sec-WebSocket-Version": "13",
			"Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
		},
	)

	try:
		with urllib.request.urlopen(
			other_device_request, timeout=5
		) as response:
			other_ws_status = response.status
	except urllib.error.HTTPError as error:
		other_ws_status = error.code

	check(
		other_ws_status == 401,
		"Phone credential cannot access another device",
	)

	if previous_phone_credential:
		print("\nTesting previous phone credential after replacement...")

		status, _ = call(
			"GET",
			"/pairing/status" + session_query,
			token=previous_phone_credential,
		)

		check(
			status == 401,
			"Previous phone credential is rejected after replacement",
		)

	print("\nPairing flow test completed successfully.")


if __name__ == "__main__":
	main()
