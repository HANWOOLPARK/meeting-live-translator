export const VIEWER_SESSION_COOKIE = "mlt_viewer_session";

export function normalizeEmail(value: unknown) {
  const email = String(value ?? "").trim().toLowerCase();
  if (email.length < 3 || email.length > 254) return null;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;
  return email;
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
