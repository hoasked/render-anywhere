export type PairingStatus = 'pending' | 'requested' | 'approved' | 'completed';

export interface PairingSession {
	id: string;
	deviceId: string;
	tokenHash: string;
	createdAt: number;
	expiresAt: number;
	status: PairingStatus;
	phoneCredentialHash?: string;
}

export const PAIRING_TTL_MS = 3 * 60 * 1000;

export async function hashToken(token: string): Promise<string> {
	const bytes = new TextEncoder().encode(token);
	const digest = await crypto.subtle.digest('SHA-256', bytes);

	return Array.from(new Uint8Array(digest))
		.map((byte) => byte.toString(16).padStart(2, '0'))
		.join('');
}

export function generateToken(): string {
	const bytes = crypto.getRandomValues(new Uint8Array(32));

	return Array.from(bytes)
		.map((byte) => byte.toString(16).padStart(2, '0'))
		.join('');
}

export async function createPairingSession(
	storage: DurableObjectStorage,
	deviceId: string,
): Promise<{ session: PairingSession; token: string }> {
	const token = generateToken();
	const now = Date.now();

	const session: PairingSession = {
		id: crypto.randomUUID(),
		deviceId,
		tokenHash: await hashToken(token),
		createdAt: now,
		expiresAt: now + PAIRING_TTL_MS,
		status: 'pending',
	};

	await storage.transaction(async (txn) => {
		const previousId = await txn.get<string>('current_pairing_session_id');

		if (previousId) {
			await txn.delete(`pairing:${previousId}`);
		}

		await txn.put(`pairing:${session.id}`, session);
		await txn.put('current_pairing_session_id', session.id);
	});

	return { session, token };
}

export async function getPairingSession(storage: DurableObjectStorage, sessionId: string): Promise<PairingSession | null> {
	const session = await storage.get<PairingSession>(`pairing:${sessionId}`);

	if (!session || session.expiresAt <= Date.now()) {
		if (session) {
			await storage.delete(`pairing:${sessionId}`);
		}

		return null;
	}

	return session;
}

export async function requestPairing(
	storage: DurableObjectStorage,
	sessionId: string,
	qrToken: string,
	phoneCredential: string,
): Promise<PairingSession | null> {
	const suppliedTokenHash = await hashToken(qrToken);
	const phoneCredentialHash = await hashToken(phoneCredential);

	return storage.transaction(async (txn) => {
		const key = `pairing:${sessionId}`;
		const session = await txn.get<PairingSession>(key);

		if (!session || session.expiresAt <= Date.now() || session.status !== 'pending' || suppliedTokenHash !== session.tokenHash) {
			return null;
		}

		const updated: PairingSession = {
			...session,
			status: 'requested',
			phoneCredentialHash,
		};

		await txn.put(key, updated);

		return updated;
	});
}

export async function approvePairing(storage: DurableObjectStorage, sessionId: string): Promise<PairingSession | null> {
	return storage.transaction(async (txn) => {
		const key = `pairing:${sessionId}`;
		const session = await txn.get<PairingSession>(key);

		if (!session || session.expiresAt <= Date.now() || session.status !== 'requested' || !session.phoneCredentialHash) {
			return null;
		}

		const updated: PairingSession = {
			...session,
			status: 'approved',
		};

		await txn.put(key, updated);

		// The existing phone remains active until completion.
		return updated;
	});
}

export async function completePairing(storage: DurableObjectStorage, sessionId: string, phoneCredential: string): Promise<boolean> {
	const suppliedHash = await hashToken(phoneCredential);

	return storage.transaction(async (txn) => {
		const key = `pairing:${sessionId}`;
		const session = await txn.get<PairingSession>(key);

		if (
			!session ||
			session.expiresAt <= Date.now() ||
			session.status !== 'approved' ||
			!session.phoneCredentialHash ||
			suppliedHash !== session.phoneCredentialHash
		) {
			return false;
		}

		const updated: PairingSession = {
			...session,
			status: 'completed',
		};

		// Activate the new credential and complete pairing atomically.
		await txn.put('active_phone_credential_hash', suppliedHash);
		await txn.put(key, updated);

		return true;
	});
}
