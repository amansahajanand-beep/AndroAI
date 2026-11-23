/**
 * DEV-ONLY demo authentication store (NEXT_PUBLIC_API_MODE=mock).
 *
 * There is no backend yet, so "accounts" and the active session live in
 * localStorage on this device only. This is demo auth for frontend
 * development — not a security boundary. The password "hash" below is a
 * non-cryptographic checksum, only meant to avoid keeping raw passwords in
 * plain sight in localStorage.
 *
 * Swap-out path: once a real backend exists, the handlers in `transport.ts`
 * that call into this file get replaced by real `auth.*` / `users.*` calls
 * through the live HTTP transport (see `../transport.ts`). Nothing outside
 * `lib/api/mock/**` knows this store exists.
 */
import type { User, UserRole } from "@apppilot/contracts";

const USERS_KEY = "apppilot.demo.users";
const SESSION_KEY = "apppilot.demo.session";
const RESET_TOKENS_KEY = "apppilot.demo.resetTokens";

const DAY_MS = 86_400_000;

export interface DemoUser {
  id: string;
  name: string;
  email: string;
  passwordHash: string;
  avatarUrl: string | null;
  role: UserRole;
  emailVerified: boolean;
  createdAt: string;
}

interface DemoSession {
  userId: string;
  expiresAt: string;
}

interface ResetToken {
  email: string;
  expiresAt: string;
}

const hasStorage = () => typeof window !== "undefined" && !!window.localStorage;

function read<T>(key: string, fallback: T): T {
  if (!hasStorage()) return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  if (!hasStorage()) return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or blocked (private mode): demo auth just won't persist.
  }
}

/** FNV-1a — fast, deterministic, NOT secure. Good enough to avoid plaintext-in-localStorage. */
function hashPassword(password: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < password.length; i++) {
    h ^= password.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16);
}

let idSeq = 1;
const newId = () => `demo_u_${Date.now().toString(36)}_${idSeq++}`;

function loadUsers(): DemoUser[] {
  return read<DemoUser[]>(USERS_KEY, []);
}

function saveUsers(users: DemoUser[]) {
  write(USERS_KEY, users);
}

/** Seeds one ready-to-use account so the login screen works before anyone registers. */
export function seedDemoUsersIfEmpty() {
  if (!hasStorage()) return;
  const existing = loadUsers();
  if (existing.length > 0) return;
  const seeded: DemoUser = {
    id: newId(),
    name: "Mira Kapoor",
    email: "mira@example.dev",
    passwordHash: hashPassword("Demo12345!"),
    avatarUrl: null,
    role: "admin",
    emailVerified: true,
    createdAt: new Date().toISOString(),
  };
  saveUsers([seeded]);
}

export function findByEmail(email: string): DemoUser | undefined {
  const needle = email.trim().toLowerCase();
  return loadUsers().find((u) => u.email.toLowerCase() === needle);
}

export function findById(id: string): DemoUser | undefined {
  return loadUsers().find((u) => u.id === id);
}

export class EmailTakenError extends Error {}

export function createDemoUser(input: { name: string; email: string; password: string }): DemoUser {
  const users = loadUsers();
  if (users.some((u) => u.email.toLowerCase() === input.email.trim().toLowerCase())) {
    throw new EmailTakenError(`An account with ${input.email} already exists.`);
  }
  const user: DemoUser = {
    id: newId(),
    name: input.name,
    email: input.email.trim(),
    passwordHash: hashPassword(input.password),
    avatarUrl: null,
    role: "user",
    emailVerified: false,
    createdAt: new Date().toISOString(),
  };
  saveUsers([...users, user]);
  return user;
}

export function verifyCredentials(email: string, password: string): DemoUser | null {
  const user = findByEmail(email);
  if (!user || user.passwordHash !== hashPassword(password)) return null;
  return user;
}

export function updateDemoUser(id: string, patch: Partial<Pick<DemoUser, "name" | "avatarUrl">>): DemoUser | undefined {
  const users = loadUsers();
  const idx = users.findIndex((u) => u.id === id);
  const existing = users[idx];
  if (idx === -1 || !existing) return undefined;
  const updated: DemoUser = { ...existing, ...patch };
  users[idx] = updated;
  saveUsers(users);
  return updated;
}

export function setDemoPassword(id: string, newPassword: string): boolean {
  const users = loadUsers();
  const idx = users.findIndex((u) => u.id === id);
  const existing = users[idx];
  if (idx === -1 || !existing) return false;
  users[idx] = { ...existing, passwordHash: hashPassword(newPassword) };
  saveUsers(users);
  return true;
}

export function toSessionUser(user: DemoUser): User {
  return {
    id: user.id,
    name: user.name,
    email: user.email,
    avatarUrl: user.avatarUrl,
    role: user.role,
    emailVerified: user.emailVerified,
    createdAt: user.createdAt,
  };
}

/* ---------------- session ---------------- */

export function getActiveSession(): { session: DemoSession; user: DemoUser } | null {
  const session = read<DemoSession | null>(SESSION_KEY, null);
  if (!session) return null;
  if (new Date(session.expiresAt).getTime() <= Date.now()) {
    clearSession();
    return null;
  }
  const user = findById(session.userId);
  if (!user) {
    clearSession();
    return null;
  }
  return { session, user };
}

export function startSession(userId: string, remember = true): { expiresAt: string } {
  const expiresAt = new Date(Date.now() + (remember ? 30 : 1) * DAY_MS).toISOString();
  write(SESSION_KEY, { userId, expiresAt } satisfies DemoSession);
  return { expiresAt };
}

export function clearSession() {
  if (!hasStorage()) return;
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore
  }
}

/* ---------------- forgot / reset password ---------------- */

function loadResetTokens(): Record<string, ResetToken> {
  return read<Record<string, ResetToken>>(RESET_TOKENS_KEY, {});
}

function saveResetTokens(tokens: Record<string, ResetToken>) {
  write(RESET_TOKENS_KEY, tokens);
}

/** Returns a token only when the email matches an account; callers must still respond generically to avoid enumeration. */
export function createResetTokenIfAccountExists(email: string): string | null {
  const user = findByEmail(email);
  if (!user) return null;
  const token = `${newId()}_${hashPassword(`${email}:${Date.now()}`)}`;
  const tokens = loadResetTokens();
  tokens[token] = { email: user.email, expiresAt: new Date(Date.now() + 30 * 60_000).toISOString() };
  saveResetTokens(tokens);
  if (typeof window !== "undefined") {
    // No email service in frontend-only demo mode: surface the link for manual testing.
    console.info(`[demo auth] Password reset link for ${user.email}: /reset-password?token=${token}`);
  }
  return token;
}

export function consumeResetToken(token: string, newPassword: string): boolean {
  const tokens = loadResetTokens();
  const entry = tokens[token];
  if (!entry || new Date(entry.expiresAt).getTime() <= Date.now()) return false;
  const user = findByEmail(entry.email);
  if (!user) return false;
  setDemoPassword(user.id, newPassword);
  delete tokens[token];
  saveResetTokens(tokens);
  return true;
}
