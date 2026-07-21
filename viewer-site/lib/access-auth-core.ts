export const VIEWER_SESSION_COOKIE = "mlt_viewer_session";
export const OTP_CODE_LENGTH = 6;

export function normalizeEmail(value: unknown) {
  const email = String(value ?? "").trim().toLowerCase();
  if (email.length < 3 || email.length > 254) return null;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;
  return email;
}

export function validVerificationCode(value: unknown) {
  const code = String(value ?? "").replace(/\s+/g, "");
  return /^\d{6}$/.test(code) ? code : null;
}

export function generateVerificationCode() {
  const digits: number[] = [];
  while (digits.length < OTP_CODE_LENGTH) {
    const bytes = new Uint8Array(OTP_CODE_LENGTH * 2);
    crypto.getRandomValues(bytes);
    for (const byte of bytes) {
      if (byte >= 250) continue;
      digits.push(byte % 10);
      if (digits.length === OTP_CODE_LENGTH) break;
    }
  }
  return digits.join("");
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

export function constantTimeEqual(left: string, right: string) {
  const maximum = Math.max(left.length, right.length);
  let difference = left.length ^ right.length;
  for (let index = 0; index < maximum; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0;
}

export async function verificationCodeHash(
  secret: string,
  roomId: string,
  challengeId: string,
  email: string,
  code: string,
) {
  return hmacHex(secret, `mlt-otp-v1\n${roomId}\n${challengeId}\n${email}\n${code}`);
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
