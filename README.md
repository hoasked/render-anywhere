# Render Anywhere

Keep up with your Blender renders remotely from your phone.

Render Anywhere is an open-source project designed to let you check render progress and system statistics on a phone while Blender renders on your PC. The project combines a Blender add-on, a PC-side monitoring script, a cloud relay, and a mobile app.

> **Project status:** In active development. The current setup has been tested with Blender 5.2 on Windows and an NVIDIA GPU. Other systems and configurations may require additional setup or testing.

## Features

- **Live render progress** — view the current frame, sample progress, and overall animation progress where available.
- **Time estimates** — monitor elapsed time and estimated remaining time.
- **System statistics** — view available CPU, RAM, and GPU metrics.
- **Remote monitoring** — receive updates on your phone through a cloud relay rather than relying exclusively on your local Wi-Fi.
- **Self-hostable infrastructure** — configure your own Cloudflare Worker deployment.
- **Open source** — inspect, modify, and contribute to the project.

Available metrics depend on the Blender version, render engine, hardware, and installed dependencies.

## How it works

```text
Blender
   │
   ▼
Render Anywhere add-on
   │
   ▼
PC-side monitoring script
   │
   ▼
Cloudflare Worker relay
   │
   ▼
Mobile app
```

The Blender add-on collects render information, while the PC-side monitor gathers available system statistics. The relay transports updates to the mobile app.

The cloud relay is separate from the monitoring software running on the PC.

## Project structure

```text
render-anywhere/
├── addon/
│   └── __init__.py
├── src/
├── package.json
├── package-lock.json
├── wrangler.jsonc
├── pair_production.py
├── test_pairing.py
└── README.md
```

The repository contains the Blender add-on and cloud relay code, along with pairing utilities. The PC-side monitor and mobile application may be maintained in separate directories or components depending on the current project layout.

## Requirements

Before setting up your own deployment, prepare:

- A Windows, Linux, or macOS PC capable of running Blender.
- A compatible Blender installation.
- Python for the PC-side monitoring script.
- Node.js and npm for the Cloudflare Worker development environment.
- A Cloudflare account for deploying your own relay.
- A compatible mobile app environment or a built version of the app.

Some GPU statistics require additional platform-specific dependencies. NVIDIA GPU monitoring may require the NVIDIA Management Library Python bindings and a compatible NVIDIA driver. CPU and memory metrics may require `psutil`.

## Getting started

### 1. Download the repository

Clone the repository and enter the project directory:

```bash
git clone https://github.com/hoasked/render-anywhere.git
cd render-anywhere
```

If the repository's cloud code is in a subdirectory, enter that directory before running the following cloud setup commands.

### 2. Set up the cloud relay

Install the Node.js dependencies:

```bash
npm install
```

Configure the Cloudflare Worker using the supplied `wrangler.jsonc` configuration.

For local development, create a local `.dev.vars` file with a randomly generated, private relay secret:

```dotenv
RELAY_SECRET=replace-with-your-own-secret
```

Start the local Worker using the development command configured in `package.json`, commonly:

```bash
npx wrangler dev
```

Follow the project's Cloudflare configuration and logs to confirm that the Worker starts successfully.

### 3. Configure your own production relay

To monitor renders over the internet, deploy your own Worker and configure the PC-side monitor and mobile app to use its URL.

Set the relay secret in your deployment's secret configuration. Keep the secret private and separate from the public repository.

Do not assume the repository owner's deployed relay is a public service for general use. Each deployment should use its own configuration and credentials.

### 4. Install the Blender add-on

Install the add-on from the repository's `addon` directory, following the directory structure expected by Blender.

Enable the add-on in Blender and turn on Render Anywhere monitoring in its panel.

If your Blender version does not load the add-on automatically, check the installation directory and Blender's console for errors.

### 5. Configure the PC-side monitor

Set up the PC-side monitoring script with the Python dependencies it requires. Configure it to use your relay URL and the same private relay secret expected by your deployment.

Start the monitoring process before or while rendering. Keep it running for the duration of the render.

Never publish your relay secret, phone credentials, or local environment files.

### 6. Connect the mobile app

Build or install the mobile app using the instructions provided by its project directory.

Configure it to connect to your relay and complete the supported pairing flow. The PC and phone must use matching deployment configuration and valid credentials.

### 7. Test a render

Start a small test render in Blender and check that the mobile app receives updates.

Verify that frame progress, sample progress, timing information, and available system statistics change as the render proceeds.

If the phone remains idle, check the Blender add-on, PC-side monitor, relay logs, and pairing configuration.

## Security

- Never commit `.dev.vars`, phone credentials, access tokens, or private keys.
- Keep dependencies and deployment configuration up to date.
- Review the authentication and pairing implementation before exposing a deployment to other users.
