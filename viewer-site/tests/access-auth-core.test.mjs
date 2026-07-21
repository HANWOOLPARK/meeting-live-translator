import assert from "node:assert/strict";
import test from "node:test";
import {
  VIEWER_SESSION_COOKIE,
  clearViewerSessionCookie,
  constantTimeEqual,
  cookieValue,
  generateVerificationCode,
  normalizeEmail,
  validVerificationCode,
  verificationCodeHash,
  viewerSessionCookie,
} from "../lib/access-auth-core.ts";

test("normalizes email addresses and rejects malformed input", () => {
  assert.equal(normalizeEmail("  Person@Example.COM "), "person@example.com");
  assert.equal(normalizeEmail("missing-at.example.com"), null);
  assert.equal(normalizeEmail("person@localhost"), null);
  assert.equal(normalizeEmail("a".repeat(255)), null);
});

test("verification codes are six decimal digits", () => {
  const generated = new Set();
  for (let index = 0; index < 50; index += 1) {
    const code = generateVerificationCode();
    assert.match(code, /^\d{6}$/);
    assert.equal(validVerificationCode(code), code);
    generated.add(code);
  }
  assert.ok(generated.size > 1);
  assert.equal(validVerificationCode("12345"), null);
  assert.equal(validVerificationCode("12a456"), null);
});

test("code hashes are deterministic and bound to room, challenge, and email", async () => {
  const first = await verificationCodeHash("secret", "room-a", "challenge-a", "a@example.com", "123456");
  const again = await verificationCodeHash("secret", "room-a", "challenge-a", "a@example.com", "123456");
  const otherRoom = await verificationCodeHash("secret", "room-b", "challenge-a", "a@example.com", "123456");
  assert.equal(first, again);
  assert.notEqual(first, otherRoom);
  assert.equal(constantTimeEqual(first, again), true);
  assert.equal(constantTimeEqual(first, otherRoom), false);
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
