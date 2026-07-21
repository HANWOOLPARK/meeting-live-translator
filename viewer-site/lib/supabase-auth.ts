import { env } from "cloudflare:workers";
import { normalizeEmail } from "./access-auth-core";

const SUPABASE_REQUEST_TIMEOUT_MS = 8_000;
const PROFILE_TABLE = "whykaigi_attendee_profiles";
const ACCESS_LOG_TABLE = "whykaigi_room_access_logs";

type RuntimeEnv = typeof env & {
  MLT_ACCESS_SIGNING_SECRET?: string;
  SUPABASE_URL?: string;
  SUPABASE_PUBLISHABLE_KEY?: string;
};

type SupabaseUserPayload = {
  id?: unknown;
  email?: unknown;
  email_confirmed_at?: unknown;
  app_metadata?: {
    provider?: unknown;
    providers?: unknown;
  } | null;
  user_metadata?: {
    avatar_url?: unknown;
    full_name?: unknown;
    name?: unknown;
  } | null;
  identities?: Array<{ provider?: unknown }> | null;
};

export type VerifiedSupabaseIdentity = {
  accessToken: string;
  userId: string;
  email: string;
  displayName: string;
  avatarUrl: string;
  provider: "google";
};

function runtime() {
  return env as RuntimeEnv;
}

function cleanText(value: unknown, maximum: number) {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, maximum).trim();
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
  if (!url || !publishableKey || publishableKey.length > 2_048) return null;
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

function identityUsesGoogle(user: SupabaseUserPayload) {
  const providers = Array.isArray(user.app_metadata?.providers)
    ? user.app_metadata?.providers.map((item) => cleanText(item, 32))
    : [];
  const identityProviders = Array.isArray(user.identities)
    ? user.identities.map((identity) => cleanText(identity.provider, 32))
    : [];
  return cleanText(user.app_metadata?.provider, 32) === "google"
    || providers.includes("google")
    || identityProviders.includes("google");
}

export async function verifySupabaseGoogleIdentity(
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
  const userId = cleanText(user.id, 64);
  const email = normalizeEmail(user.email);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(userId)) {
    return null;
  }
  if (!email || !user.email_confirmed_at || !identityUsesGoogle(user)) return null;

  return {
    accessToken,
    userId,
    email,
    displayName: cleanText(
      user.user_metadata?.full_name ?? user.user_metadata?.name,
      120,
    ),
    avatarUrl: cleanText(user.user_metadata?.avatar_url, 500),
    provider: "google",
  };
}

async function supabaseRestRequest(
  identity: VerifiedSupabaseIdentity,
  path: string,
  body: unknown,
  prefer: string,
) {
  const config = supabasePublicConfig();
  if (!config) return false;
  const response = await fetch(`${config.url}/rest/v1/${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${identity.accessToken}`,
      apikey: config.publishableKey,
      "Content-Type": "application/json",
      Prefer: prefer,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(SUPABASE_REQUEST_TIMEOUT_MS),
  });
  return response.ok;
}

export async function recordSupabaseRoomAccess(
  roomId: string,
  identity: VerifiedSupabaseIdentity,
) {
  const now = new Date().toISOString();
  const profileSynced = await supabaseRestRequest(
    identity,
    `${PROFILE_TABLE}?on_conflict=user_id`,
    {
      user_id: identity.userId,
      email: identity.email,
      display_name: identity.displayName,
      avatar_url: identity.avatarUrl,
      provider: identity.provider,
      last_seen_at: now,
    },
    "resolution=merge-duplicates,return=minimal",
  ).catch(() => false);
  const logSynced = await supabaseRestRequest(
    identity,
    ACCESS_LOG_TABLE,
    {
      room_id: roomId,
      user_id: identity.userId,
      email: identity.email,
      display_name: identity.displayName,
      provider: identity.provider,
      event_type: "access_granted",
      occurred_at: now,
    },
    "return=minimal",
  ).catch(() => false);
  return profileSynced && logSynced;
}
