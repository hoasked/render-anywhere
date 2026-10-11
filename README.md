# Render Anywhere

**Keep up with your Blender renders remotely, from your phone.**

Render Anywhere is a personal software project exploring how to monitor Blender renders remotely. It uses a Cloudflare Workers relay and Durable Objects to support communication between a rendering PC and remote clients, with a secure phone-pairing workflow.

> **Project status: In development.** The local relay, authentication checks, and phone-pairing flow have been tested locally.

## Features

- **Render monitoring:** Designed to report render progress and system statistics from a PC running Blender.
- **Cloud relay:** Uses Cloudflare Workers and Durable Objects to route requests by device ID.
- **Phone pairing:** Implements temporary pairing sessions so a phone can request access and the PC can approve it.
- **Credential security:** Uses hashed phone credentials, expiring pairing sessions, and credential replacement.
- **Authentication:** Rejects unauthenticated requests and invalid phone credentials.
- **Device isolation:** Tests that a phone credential for one device cannot be used to access another.
- **Automated checks:** Includes scripts for testing authentication and the pairing workflow.

## Technology stack

| Technology | Purpose |
|---|---|
| Python | Local integration tests and the PC-side monitoring component |
| TypeScript | Cloud relay and request handling |
| Cloudflare Workers | Relay runtime |
| Cloudflare Durable Objects | Device-specific routing and state |
| WebSockets | Real-time communication |
| Node.js and npm | Development tooling and dependency management |

## Architecture

```text
Blender on rendering PC
          |
          v
PC-side monitoring component
          |
          v
Cloudflare Worker relay
          |
          v
Device-specific Durable Object
          |
          v
Paired phone / remote client
```

The PC-side monitoring component collects render information. The relay is responsible for routing communication, while the pairing workflow controls which phone credentials are accepted.

The diagram represents the intended system architecture; full remote operation has not yet been verified in production.

## Local development

### Requirements

- Windows, macOS, or Linux
- Node.js and npm
- Python 3
- A Cloudflare Wrangler development environment
- A local `.dev.vars` file containing the required `RELAY_SECRET`

### 1. Clone the repository

```bash
git clone https://github.com/hoasked/render-anywhere.git
cd render-anywhere
```

### 2. Install dependencies

```bash
npm install
```

### 3. Configure the local secret

Create a `.dev.vars` file in the project root and define a strong, private `RELAY_SECRET` value.

Never commit `.dev.vars`, publish the secret, or reuse development credentials in production.

### 4. Start the local relay

```bash
npm run dev
```

### 5. Check TypeScript

In another terminal, run:

```bash
npx tsc --noEmit
```

### 6. Run the integration checks

With the local relay running, execute:

```bash
py test_auth.py
py test_pairing.py
```

