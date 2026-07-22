import assert from "node:assert/strict";
import test from "node:test";
import {
  VIEWER_SESSION_COOKIE,
  clearViewerSessionCookie,
  cookieValue,
  hmacHex,
  normalizeEmail,
  verifiedSupabaseIdentityFromClaims,
  viewerSessionCookie,
} from "../lib/access-auth-core.ts";

const USER_ID = "4b1807f7-7539-48da-90ac-ec329e91f328";

function unsignedAccessToken(payload) {
  return [
    Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url"),
    Buffer.from(JSON.stringify(payload)).toString("base64url"),
    "test-signature-is-not-trusted-by-this-parser",
  ].join(".");
}

function verifiedUser(provider, providers = [provider]) {
  return {
    id: USER_ID,
    email: "  Person@Example.COM ",
    email_confirmed_at: "2026-07-22T00:00:00.000Z",
    is_anonymous: false,
    app_metadata: { provider, providers },
    user_metadata: { full_name: "Test Person" },
    identities: providers.map((identityProvider) => ({ provider: identityProvider })),
  };
}

test("normalizes email addresses and rejects malformed input", () => {
  assert.equal(normalizeEmail("  Person@Example.COM "), "person@example.com");
  assert.equal(normalizeEmail("missing-at.example.com"), null);
  assert.equal(normalizeEmail("person@localhost"), null);
  assert.equal(normalizeEmail("a".repeat(255)), null);
});

test("accepts confirmed Google OAuth and email Magic Link identities", () => {
  assert.deepEqual(
    verifiedSupabaseIdentityFromClaims(
      verifiedUser("google"),
      unsignedAccessToken({ sub: USER_ID, amr: [{ method: "oauth", timestamp: 100 }] }),
    ),
    { email: "person@example.com", displayName: "Test Person", provider: "google" },
  );
  assert.deepEqual(
    verifiedSupabaseIdentityFromClaims(
      verifiedUser("email"),
      unsignedAccessToken({
        sub: USER_ID,
        amr: [
          { method: "otp", timestamp: 100 },
          { method: "token_refresh", timestamp: 200 },
        ],
      }),
    ),
    { email: "person@example.com", displayName: "Test Person", provider: "email" },
  );
});

test("rejects mismatched, unconfirmed, anonymous, and malformed Supabase claims", () => {
  const googleToken = unsignedAccessToken({ sub: USER_ID, amr: [{ method: "oauth", timestamp: 100 }] });
  assert.equal(
    verifiedSupabaseIdentityFromClaims(
      verifiedUser("google"),
      unsignedAccessToken({ sub: "2ec0256e-6223-4378-b762-93e47d74a34b", amr: [{ method: "oauth" }] }),
    ),
    null,
  );
  assert.equal(
    verifiedSupabaseIdentityFromClaims({ ...verifiedUser("google"), email_confirmed_at: null }, googleToken),
    null,
  );
  assert.equal(
    verifiedSupabaseIdentityFromClaims({ ...verifiedUser("google"), is_anonymous: true }, googleToken),
    null,
  );
  assert.equal(verifiedSupabaseIdentityFromClaims(verifiedUser("google"), "not-a-jwt"), null);
});

test("fails closed when a Supabase user has a disallowed linked OAuth provider", () => {
  const linkedUser = verifiedUser("google", ["google", "github"]);
  assert.equal(
    verifiedSupabaseIdentityFromClaims(
      linkedUser,
      unsignedAccessToken({ sub: USER_ID, amr: [{ method: "oauth", timestamp: 100 }] }),
    ),
    null,
  );
});

test("audit HMACs are deterministic and bound to both secret and value", async () => {
  const first = await hmacHex("secret-a", "room-a\n192.0.2.1");
  const again = await hmacHex("secret-a", "room-a\n192.0.2.1");
  const otherSecret = await hmacHex("secret-b", "room-a\n192.0.2.1");
  const otherValue = await hmacHex("secret-a", "room-b\n192.0.2.1");
  assert.equal(first, again);
  assert.notEqual(first, otherSecret);
  assert.notEqual(first, otherValue);
  assert.match(first, /^[0-9a-f]{64}$/);
});

test("cookie parser ignores unrelated and malformed values", () => {
  assert.equal(
    cookieValue(new Request("https://example.test", { headers: { Cookie: "other=value; wanted=safe%20value" } }), "wanted"),
    "safe value",
  );
  assert.equal(
    cookieValue(new Request("https://example.test", { headers: { Cookie: "wanted=%E0%A4%A" } }), "wanted"),
    "",
  );
  assert.equal(cookieValue(new Request("https://example.test"), "wanted"), "");
});

test("viewer cookies are secure, HTTP-only, strict, and room-scoped", () => {
  const header = viewerSessionCookie("abcdefghijklmnopqrst", "token-value", 3600);
  assert.match(header, new RegExp(`^${VIEWER_SESSION_COOKIE}=`));
  assert.match(header, /Path=\/api\/rooms\/abcdefghijklmnopqrst/);
  assert.match(header, /HttpOnly/);
  assert.match(header, /Secure/);
  assert.match(header, /SameSite=Strict/);
  assert.equal(
    cookieValue(new Request("https://example.test", { headers: { Cookie: `${VIEWER_SESSION_COOKIE}=token-value` } }), VIEWER_SESSION_COOKIE),
    "token-value",
  );
  assert.match(clearViewerSessionCookie("abcdefghijklmnopqrst"), /Max-Age=0/);
});
