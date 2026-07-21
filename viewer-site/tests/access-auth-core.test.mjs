import assert from "node:assert/strict";
import test from "node:test";
import {
  VIEWER_SESSION_COOKIE,
  clearViewerSessionCookie,
  cookieValue,
  hmacHex,
  normalizeEmail,
  viewerSessionCookie,
} from "../lib/access-auth-core.ts";

test("normalizes email addresses and rejects malformed input", () => {
  assert.equal(normalizeEmail("  Person@Example.COM "), "person@example.com");
  assert.equal(normalizeEmail("missing-at.example.com"), null);
  assert.equal(normalizeEmail("person@localhost"), null);
  assert.equal(normalizeEmail("a".repeat(255)), null);
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
