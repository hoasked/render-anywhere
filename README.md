# Render Anywhere

Keep up with your Blender renders using your Android phone, when you're away from your PC.

Render Anywhere is an early-stage, open-source project made up of a Blender add-on, a Cloudflare Worker relay, a pairing utility, and an Android app. This guide explains how to install the published release and how to run your **own relay**.

> **Important:** This is an early release and setup includes manual configuration. The documented release has been tested with Blender 5.2 on Windows. Other operating systems and Blender versions may need adjustments. The hosted relay URL in the source is the maintainer's deployment, not a promise of a public multi-user service. For independent use, deploy your own Worker and configure the add-on and pairing script to use it.

## What you need

- A PC with Blender 5.2 or a compatible recent version.
- An Android phone.
- Node.js and npm.
- A Cloudflare account with Workers available.
- Python 3 on the PC for the pairing utility.
- Git, if you are cloning the source rather than downloading the release assets.

## Download the release

Open the repository's [Releases page](https://github.com/hoasked/render-anywhere/releases) and download the assets attached to the release:

- **`render-anywhere-addon.zip`** — Blender add-on.
- **`render-anywhere-android.apk`** — Android app.

Install the APK on your Android phone. Android may ask you to allow installation from the browser or file manager you used to open it. Only install an APK you trust and that you downloaded from the project's official release.

## Install the Blender add-on

1. Open Blender.
2. Open **Edit → Preferences → Add-ons** (the exact menu wording can vary by Blender version).
3. Choose **Install from Disk** and select `render-anywhere-addon.zip`.
4. Enable **Render Anywhere** if it is not enabled automatically.
5. Find its panel in the 3D Viewport sidebar (`N` key). Follow the panel's status messages when starting monitoring.

The release ZIP bundles the add-on's `websocket-client` dependency. If Blender reports an import or connection error, check Blender's console and the troubleshooting section below.

## Recommended: run your own Cloudflare relay

Each person deploying their own relay should use their own `RELAY_SECRET`. Do not share your secret with other users or commit it to Git.

### 1. Get the source

Install Git if needed, then run:

```bash
git clone https://github.com/hoasked/render-anywhere.git
cd render-anywhere
```

Install Node.js and npm, then install the Worker dependencies from the repository root (the directory containing `package.json` and `wrangler.jsonc`):

```bash
npm install
npx wrangler login
```

The supplied `wrangler.jsonc` defines the Durable Object binding and migration used by the relay. Keep this file with the Worker source.

### 2. Create a private relay secret

Generate a long random secret and keep it private. For local development, create a file named `.dev.vars` in the Worker project directory:

```dotenv
RELAY_SECRET=replace-this-with-a-long-random-secret
```

Replace the example value; do not use it literally. Keep `.dev.vars` on your own computer and do not commit it. For a production deployment, configure the secret with Wrangler instead of placing it in public source:

```bash
npx wrangler secret put RELAY_SECRET
```

When prompted, enter your own secret. Use the same secret for the Worker and the PC process that authenticates to it.

### 3. Deploy the Worker

From the directory containing `wrangler.jsonc`, run:

```bash
npm run deploy
```

Wrangler will print your Worker URL, usually similar to `https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev`. Save that URL. Use its HTTPS origin for the pairing script and its WebSocket form (`wss://...`) for the Blender add-on.

If deployment fails, check that you are logged into the intended Cloudflare account and that the Worker configuration and Durable Object migration are present.

### 4. Point the Blender add-on at your Worker

**The current release does not expose the relay URL and device ID as configurable fields.** You must edit the add-on source before using a different Worker.

1. Make a backup of the release add-on ZIP and extract it.
2. Open the add-on's `__init__.py` in a text editor.
3. Find the Worker URL in the PC connection code. Replace the existing URL:

   ```python
   url = "wss://cloud.t0257354.workers.dev/?role=pc&device_id=my-render-pc"
   ```

   with your own Worker and chosen device ID, for example:

   ```python
   url = "wss://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev/?role=pc&device_id=my-render-pc"
   ```

4. Search the file for **every** occurrence of the old Worker URL and device ID and update them consistently. Keep the `role=pc` and `device_id` query parameters.
5. Repackage the add-on so the ZIP contains the add-on folder at its top level (including `__init__.py` and the bundled `_vendor` directory), then install the edited ZIP in Blender using the installation steps above. If you already installed the unmodified add-on, disable it and replace it with your edited version.

Choose a device ID and use exactly the same value in the pairing script. The example `my-render-pc` is fine for a single PC, but change it if you need a distinct device identifier.

### 5. Make Blender inherit your relay secret

The add-on reads `RELAY_SECRET` from the environment of the Blender process. Blender must be launched from an environment that contains your secret; opening Blender before setting it will not update its environment.

On Windows, one option is to launch Blender from Command Prompt:

```bat
set "RELAY_SECRET=PASTE_YOUR_OWN_SECRET_HERE"
start "" "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

Replace the example secret and adjust the Blender executable path to match your installation. Keep this command private and do not post screenshots or logs containing the secret. If Blender is already open, close it and launch it from the configured environment.

### 6. Generate a phone credential

The Android app's initial screen asks for a **phone credential**. This is not the same as `RELAY_SECRET`.

The repository includes `pair_production.py`, which generates a random phone credential, registers it through the Worker pairing flow, and saves it to `phone_credential.txt`.

Before running it:

1. Open `pair_production.py` in a text editor.
2. Change `BASE_URL` to your Worker HTTPS origin (for example, `https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev` — no trailing slash).
3. Change `DEVICE_ID` to the exact same ID you used in the add-on URL.
4. In the same directory as `pair_production.py`, create a private `.dev.vars` file containing the same `RELAY_SECRET` that you configured on your Worker:

   ```dotenv
   RELAY_SECRET=PASTE_YOUR_OWN_SECRET_HERE
   ```

5. From that directory, run:

   ```bash
   python pair_production.py
   ```

   On some systems, use `python3 pair_production.py` instead.

The script should report that pairing completed and save the credential in `phone_credential.txt`. If it reports an HTTP error, check the Worker URL, device ID, and matching secret before retrying.

Open `phone_credential.txt` locally and copy its full contents into the phone credential field in the Android app. Do not add quotation marks or extra spaces. Keep the file private. The script generates a new credential each time it runs, so don't rerun it unnecessarily; a new pairing may replace the previous credential for that device.

### 7. Test the connection

1. Make sure the phone has the credential from `phone_credential.txt`.
2. Close and relaunch Blender from the environment containing `RELAY_SECRET`.
3. Enable Render Anywhere monitoring in Blender.
4. Start a small test render.
5. Check whether render progress appears in the Android app.

The PC, pairing script, and phone must all point to the same Worker and device ID. The Worker secret belongs only in the Worker configuration, the local `.dev.vars` file used by the pairing utility, and the environment that launches Blender. The **phone credential** belongs in the app.

## Troubleshooting

- **“Missing RELAY_SECRET” in Blender:** close Blender and relaunch it from a terminal or environment where `RELAY_SECRET` is set.
- **Worker returns 401 during pairing:** confirm that `RELAY_SECRET` in `.dev.vars` matches the secret configured on the deployed Worker.
- **Pairing script cannot connect:** check `BASE_URL`, internet access, Worker deployment status, and the `DEVICE_ID` value.
- **Phone has no updates:** confirm that the add-on uses your Worker URL and device ID, that the phone credential was generated for the same device ID, and that monitoring is enabled in Blender.
- **Add-on dependency error:** install the release ZIP with its bundled `_vendor` directory intact. Do not install only `__init__.py`.
- **Still stuck:** open an issue in the [GitHub repository](https://github.com/hoasked/render-anywhere) and include relevant error messages, but remove secrets and credentials first.

## Development

The main components are:

- `addon/` — Blender add-on source.
- `src/` — Cloudflare Worker and pairing implementation.
- `wrangler.jsonc` — Worker and Durable Object configuration.
- `pair_production.py` — utility for registering a phone credential.
- `test_pairing.py` — pairing-related tests.

Render Anywhere is in active development. Metrics and behavior may vary by Blender version, render engine, operating system, and hardware. Contributions and bug reports are welcome.
