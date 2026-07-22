export const VIEWER_SESSION_COOKIE = "mlt_viewer_session";

export function normalizeEmail(value: unknown) {
  const email = String(value ?? "").trim().toLowerCase();
  if (email.length < 3 || email.length > 254) return null;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;
  return email;
}

export type SupabaseUserPayload = {
  id?: unknown;
  email?: unknown;
  email_confirmed_at?: unknown;
  is_anonymous?: unknown;
  app_metadata?: {
    provider?: unknown;
    providers?: unknown;
  } | null;
  user_metadata?: {
    full_name?: unknown;
    name?: unknown;
  } | null;
  identities?: Array<{ provider?: unknown }> | null;
};

export type VerifiedSupabaseProvider = "google" | "email";

export type VerifiedSupabaseIdentity = {
  email: string;
  displayName: string;
  provider: VerifiedSupabaseProvider;
};

type SupabaseAccessTokenPayload = {
  sub?: unknown;
  amr?: Array<{ method?: unknown; timestamp?: unknown }> | null;
};

function cleanText(value: unknown, maximum: number) {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, maximum).trim();
}

function accessTokenPayload(accessToken: string): SupabaseAccessTokenPayload | null {
  const encoded = accessToken.split(".")[1];
  if (!encoded) return null;
  try {
    const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as SupabaseAccessTokenPayload;
  } catch {
    return null;
  }
}

function verifiedProvider(
  user: SupabaseUserPayload,
  token: SupabaseAccessTokenPayload,
): VerifiedSupabaseProvider | null {
  const metadataProviders = Array.isArray(user.app_metadata?.providers)
    ? user.app_metadata.providers
    : [];
  const identityProviders = Array.isArray(user.identities)
    ? user.identities.map((identity) => identity.provider)
    : [];
  const providers = [user.app_metadata?.provider, ...metadataProviders, ...identityProviders]
    .map((provider) => cleanText(provider, 32).toLowerCase())
    .filter(Boolean);
  if (
    providers.length === 0
    || providers.some((provider) => provider !== "google" && provider !== "email")
  ) return null;
  const allowed = new Set(providers as VerifiedSupabaseProvider[]);
  const methods = Array.isArray(token.amr)
    ? [...token.amr]
        .sort((left, right) => Number(right.timestamp) - Number(left.timestamp))
        .map((entry) => cleanText(entry.method, 32).toLowerCase())
    : [];

  for (const method of methods) {
    if (method === "token_refresh" || method === "totp") continue;
    if (method === "oauth") return allowed.has("google") ? "google" : null;
    if ([
      "email/signup",
      "invite",
      "magiclink",
      "otp",
      "password",
      "recovery",
    ].includes(method)) {
      return allowed.has("email") ? "email" : null;
    }
    return null;
  }

  return allowed.size === 1 ? [...allowed][0] ?? null : null;
}

export function verifiedSupabaseIdentityFromClaims(
  user: SupabaseUserPayload,
  accessToken: string,
): VerifiedSupabaseIdentity | null {
  const userId = cleanText(user.id, 64);
  const email = normalizeEmail(user.email);
  const confirmedAt = typeof user.email_confirmed_at === "string"
    ? cleanText(user.email_confirmed_at, 64)
    : "";
  const token = accessTokenPayload(accessToken);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(userId)
    || !email
    || !confirmedAt
    || user.is_anonymous === true
    || !token
    || cleanText(token.sub, 64) !== userId
  ) return null;
  const provider = verifiedProvider(user, token);
  if (!provider) return null;

  return {
    email,
    displayName: cleanText(
      user.user_metadata?.full_name ?? user.user_metadata?.name,
      120,
    ),
    provider,
  };
}

function toHex(bytes: Uint8Array) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function hmacHex(secret: string, value: string) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(value));
  return toHex(new Uint8Array(signature));
}

export function cookieValue(request: Request, name: string) {
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const [rawName, ...rawValue] = part.trim().split("=");
    if (rawName !== name) continue;
    try {
      return decodeURIComponent(rawValue.join("="));
    } catch {
      return "";
    }
  }
  return "";
}

export function viewerSessionCookie(roomId: string, token: string, maxAgeSeconds: number) {
  const maxAge = Math.max(1, Math.floor(maxAgeSeconds));
  return `${VIEWER_SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/api/rooms/${roomId}; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}

export function clearViewerSessionCookie(roomId: string) {
  return `${VIEWER_SESSION_COOKIE}=; Path=/api/rooms/${roomId}; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
}
