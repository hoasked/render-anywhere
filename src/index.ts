import { DurableObject } from 'cloudflare:workers';
import { createPairingSession, hashToken, type PairingSession } from './pairing';

declare global {
	interface Env {
		RELAY_SECRET: string;
	}
}

type ConnectionRole = 'pc' | 'phone';

interface ConnectionInfo {
	role: ConnectionRole;
	deviceId: string;
}

function jsonResponse(data: unknown, status = 200): Response {
	return new Response(JSON.stringify(data), {
		status,
		headers: { 'Content-Type': 'application/json' },
	});
}

function bearerToken(request: Request): string | null {
	const header = request.headers.get('Authorization');
	if (!header?.startsWith('Bearer ')) return null;
	return header.slice(7);
}

async function isRegisteredPc(storage: DurableObjectStorage, bearer: string | null): Promise<boolean> {
	if (!bearer) return false;

	const storedHash = await storage.get<string>('pc_credential_hash');
	if (!storedHash) return false;

	return (await hashToken(bearer)) === storedHash;
}

export class MyDurableObject extends DurableObject<Env> {
	private connections = new Map<WebSocket, ConnectionInfo>();

	constructor(ctx: DurableObjectState, env: Env) {
		super(ctx, env);

		for (const ws of this.ctx.getWebSockets()) {
			const info = ws.deserializeAttachment() as ConnectionInfo | null;
			if (info) this.connections.set(ws, info);
		}

		this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
	}

	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);
		const path = url.pathname;
		const deviceId = url.searchParams.get('device_id');
		const sessionId = url.searchParams.get('session_id');
		const bearer = bearerToken(request);
		const isPc = bearer !== null && bearer === this.env.RELAY_SECRET;

		// Create a short-lived QR pairing session. PC authentication required.
		if (path === '/pairing/session' && request.method === 'POST') {
			if (!isPc) {
				return new Response('Unauthorized', { status: 401 });
			}
			if (!deviceId) {
				return new Response('Missing device_id.', { status: 400 });
			}

			const { session, token } = await createPairingSession(this.ctx.storage, deviceId);

			return jsonResponse(
				{
					session_id: session.id,
					token,
					expires_at: session.expiresAt,
				},
				201,
			);
		}

		// A phone claims the QR token and proposes its own random credential.
		if (path === '/pairing/request' && request.method === 'POST') {
			if (!sessionId) {
				return new Response('Missing session_id.', { status: 400 });
			}

			let body: { token?: unknown; phone_credential?: unknown };

			try {
				const rawBody = await request.text();
				body = JSON.parse(rawBody);
			} catch {
				return new Response('Invalid JSON.', { status: 400 });
			}

			if (typeof body !== 'object' || body === null || Array.isArray(body)) {
				return new Response('Invalid JSON.', { status: 400 });
			}
			if (
				typeof body.token !== 'string' ||
				typeof body.phone_credential !== 'string' ||
				body.token.length < 32 ||
				body.phone_credential.length < 32
			) {
				return new Response('Invalid pairing credentials.', {
					status: 400,
				});
			}

			const tokenHash = await hashToken(body.token);
			const phoneHash = await hashToken(body.phone_credential);

			const result = await this.ctx.storage.transaction(async (txn) => {
				const currentId = await txn.get<string>('current_pairing_session_id');
				if (currentId !== sessionId) return 'invalid';

				const key = `pairing:${sessionId}`;
				const session = await txn.get<PairingSession>(key);

				if (!session || session.expiresAt <= Date.now()) {
					return 'expired';
				}
				if (session.status !== 'pending' || tokenHash !== session.tokenHash) {
					return 'invalid';
				}

				const updated: PairingSession = {
					...session,
					status: 'requested',
					phoneCredentialHash: phoneHash,
				};
				await txn.put(key, updated);
				return 'requested';
			});

			if (result === 'expired') {
				return jsonResponse({ error: 'Pairing session expired.' }, 410);
			}
			if (result !== 'requested') {
				return jsonResponse({ error: 'Invalid or already-used QR.' }, 400);
			}

			return jsonResponse({ status: 'requested' }, 202);
		}

		// PC checks request status; phone may check using its proposed credential.
		if (path === '/pairing/status' && request.method === 'GET') {
			if (!sessionId) {
				return new Response('Missing session_id.', { status: 400 });
			}

			const currentId = await this.ctx.storage.get<string>('current_pairing_session_id');
			if (currentId !== sessionId) {
				return jsonResponse({ error: 'Session unavailable.' }, 404);
			}

			const session = await this.ctx.storage.get<PairingSession>(`pairing:${sessionId}`);
			if (!session || session.expiresAt <= Date.now()) {
				return jsonResponse({ error: 'Session expired.' }, 410);
			}

			if (!isPc) {
				const phoneHash = bearer ? await hashToken(bearer) : '';
				if (!session.phoneCredentialHash || phoneHash !== session.phoneCredentialHash) {
					return new Response('Unauthorized', { status: 401 });
				}
			}

			return jsonResponse({
				session_id: session.id,
				status: session.status,
				expires_at: session.expiresAt,
			});
		}

		// Only the authenticated PC can approve a phone.
		if (path === '/pairing/approve' && request.method === 'POST') {
			if (!isPc) {
				return new Response('Unauthorized', { status: 401 });
			}
			if (!sessionId) {
				return new Response('Missing session_id.', { status: 400 });
			}

			const result = await this.ctx.storage.transaction(async (txn) => {
				const currentId = await txn.get<string>('current_pairing_session_id');
				if (currentId !== sessionId) return 'invalid';

				const key = `pairing:${sessionId}`;
				const session = await txn.get<PairingSession>(key);

				if (!session || session.expiresAt <= Date.now()) {
					return 'expired';
				}
				if (session.status !== 'requested' || !session.phoneCredentialHash) {
					return 'invalid';
				}

				await txn.put(key, { ...session, status: 'approved' });
				return 'approved';
			});

			if (result === 'expired') {
				return jsonResponse({ error: 'Pairing session expired.' }, 410);
			}
			if (result !== 'approved') {
				return jsonResponse({ error: 'No pending request.' }, 409);
			}

			return jsonResponse({ status: 'approved' });
		}

		// Reject a request without changing the existing phone credential.
		if (path === '/pairing/reject' && request.method === 'POST') {
			if (!isPc) {
				return new Response('Unauthorized', { status: 401 });
			}
			if (!sessionId) {
				return new Response('Missing session_id.', { status: 400 });
			}

			const rejected = await this.ctx.storage.transaction(async (txn) => {
				const currentId = await txn.get<string>('current_pairing_session_id');
				if (currentId !== sessionId) return false;

				const key = `pairing:${sessionId}`;
				const session = await txn.get<PairingSession>(key);
				if (!session || session.expiresAt <= Date.now() || session.status !== 'requested') {
					return false;
				}

				await txn.delete(key);
				await txn.delete('current_pairing_session_id');
				return true;
			});

			if (!rejected) {
				return jsonResponse({ error: 'No pending request.' }, 409);
			}
			return jsonResponse({ status: 'rejected' });
		}

		// Activate the new phone only after the PC approved it.
		if (path === '/pairing/complete' && request.method === 'POST') {
			if (!sessionId || !bearer) {
				return new Response('Missing pairing credentials.', {
					status: 400,
				});
			}

			const phoneHash = await hashToken(bearer);
			const completed = await this.ctx.storage.transaction(async (txn) => {
				const currentId = await txn.get<string>('current_pairing_session_id');
				if (currentId !== sessionId) return false;

				const key = `pairing:${sessionId}`;
				const session = await txn.get<PairingSession>(key);

				if (!session || session.expiresAt <= Date.now() || session.status !== 'approved' || session.phoneCredentialHash !== phoneHash) {
					return false;
				}

				await txn.put('active_phone_credential_hash', phoneHash);
				await txn.put(key, { ...session, status: 'completed' });
				return true;
			});

			if (!completed) {
				return jsonResponse(
					{
						error: 'Pairing is not approved or has expired.',
					},
					409,
				);
			}

			// Close any previously connected phone after replacement.
			for (const [client, clientInfo] of this.connections) {
				if (clientInfo.role === 'phone' && clientInfo.deviceId === deviceId && client.readyState === WebSocket.READY_STATE_OPEN) {
					try {
						client.close(4001, 'Phone replaced');
					} catch {
						// Ignore connections that are already closing.
					}
				}
			}

			return jsonResponse({ status: 'completed' });
		}

		// Existing health check and WebSocket relay.
		if (request.headers.get('Upgrade') !== 'websocket') {
			if (!isPc) {
				return new Response('Unauthorized', { status: 401 });
			}
			return new Response('Render Anywhere relay is online.', {
				status: 200,
			});
		}

		const role = url.searchParams.get('role') as ConnectionRole | null;
		if (role !== 'pc' && role !== 'phone') {
			return new Response('Invalid role.', { status: 400 });
		}
		if (!deviceId) {
			return new Response('Missing device_id.', { status: 400 });
		}

		if (role === 'pc' && !isPc) {
			return new Response('Unauthorized', { status: 401 });
		}

		if (role === 'phone') {
			if (!bearer) {
				return new Response('Unauthorized', { status: 401 });
			}

			const suppliedHash = await hashToken(bearer);
			const activeHash = await this.ctx.storage.get<string>('active_phone_credential_hash');

			if (!activeHash || suppliedHash !== activeHash) {
				return new Response('Unauthorized', { status: 401 });
			}
		}

		const pair = new WebSocketPair();
		const [client, server] = Object.values(pair);

		this.ctx.acceptWebSocket(server);

		const info: ConnectionInfo = { role, deviceId };
		server.serializeAttachment(info);
		this.connections.set(server, info);

		if (role === 'phone') {
			const latestData = await this.ctx.storage.get<string>('latest_data');
			if (latestData) server.send(latestData);
		}

		return new Response(null, { status: 101, webSocket: client });
	}

	async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
		const info = this.connections.get(ws);
		if (!info || typeof message !== 'string') return;

		if (info.role === 'pc') {
			await this.ctx.storage.put('latest_data', message);

			for (const [client, clientInfo] of this.connections) {
				if (client !== ws && clientInfo.role === 'phone' && client.readyState === WebSocket.READY_STATE_OPEN) {
					try {
						client.send(message);
					} catch {
						// Ignore a disconnected phone.
					}
				}
			}
			return;
		}

		for (const [client, clientInfo] of this.connections) {
			if (client !== ws && clientInfo.role === 'pc' && client.readyState === WebSocket.READY_STATE_OPEN) {
				try {
					client.send(message);
				} catch {
					// Ignore a disconnected PC.
				}
			}
		}
	}

	async webSocketClose(ws: WebSocket, code: number, reason: string, wasClean: boolean) {
		this.connections.delete(ws);
		console.log('WebSocket closed:', code, reason, wasClean);
	}

	async webSocketError(ws: WebSocket, error: unknown) {
		console.error('WebSocket error:', error);
		this.connections.delete(ws);
	}
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const url = new URL(request.url);
		const deviceId = url.searchParams.get('device_id');

		if (!deviceId || !/^[a-zA-Z0-9_-]{1,128}$/.test(deviceId)) {
			return new Response('Invalid or missing device_id.', {
				status: 400,
			});
		}

		const stub = env.MY_DURABLE_OBJECT.getByName(deviceId);

		let forwardedRequest = request;

		if (request.method !== 'GET' && request.method !== 'HEAD') {
			const body = await request.arrayBuffer();

			forwardedRequest = new Request(request.url, {
				method: request.method,
				headers: request.headers,
				body,
			});
		}

		return stub.fetch(forwardedRequest);
	},
} satisfies ExportedHandler<Env>;
