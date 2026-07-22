import { env } from "cloudflare:workers";
import {
  type SupabaseUserPayload,
  type VerifiedSupabaseIdentity,
  verifiedSupabaseIdentityFromClaims,
} from "./access-auth-core";

export type { VerifiedSupabaseIdentity, VerifiedSupabaseProvider } from "./access-auth-core";

const SUPABASE_REQUEST_TIMEOUT_MS = 8_000;
const PUBLISHABLE_KEY_PATTERN = /^sb_publishable_[A-Za-z0-9_-]{20,512}$/;

type RuntimeEnv = typeof env & {
  MLT_ACCESS_SIGNING_SECRET?: string;
  SUPABASE_URL?: string;
  SUPABASE_PUBLISHABLE_KEY?: string;
};

function runtime() {
  return env as RuntimeEnv;
}

function validProjectUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname.endsWith(".supabase.co")
      ? url.origin
      : "";
  } catch {
    return "";
  }
}

export function supabasePublicConfig() {
  const url = validProjectUrl((runtime().SUPABASE_URL ?? "").trim());
  const publishableKey = (runtime().SUPABASE_PUBLISHABLE_KEY ?? "").trim();
  if (!url || !PUBLISHABLE_KEY_PATTERN.test(publishableKey)) return null;
  return { url, publishableKey };
}

export function supabaseAuthConfigured() {
  return Boolean(
    supabasePublicConfig()
      && (runtime().MLT_ACCESS_SIGNING_SECRET ?? "").trim().length >= 32,
  );
}

function bearerAccessToken(request: Request) {
  const authorization = request.headers.get("authorization") ?? "";
  const match = authorization.match(/^Bearer\s+([^\s]+)$/i);
  const token = match?.[1] ?? "";
  return token.length >= 32 && token.length <= 8_192 ? token : "";
}

export async function verifySupabaseIdentity(
  request: Request,
): Promise<VerifiedSupabaseIdentity | null> {
  const config = supabasePublicConfig();
  const accessToken = bearerAccessToken(request);
  if (!config || !accessToken) return null;

  const response = await fetch(`${config.url}/auth/v1/user`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
      apikey: config.publishableKey,
    },
    signal: AbortSignal.timeout(SUPABASE_REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) return null;

  const user = await response.json() as SupabaseUserPayload;
  return verifiedSupabaseIdentityFromClaims(user, accessToken);
}
