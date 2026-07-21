# WhyKaigi · Attendee Viewer

Invite-only browser view for live original captions, translations, and the
evidence-linked Decision Radar. The installed Windows app remains the host;
attendees need only the unguessable room URL.

## Prerequisites

- Node.js `>=22.13.0`

## Local development

```bash
pnpm install
pnpm run dev
pnpm run build
```

The runtime requires a D1 binding named `DB` and a private environment variable
named `MLT_RELAY_CREATE_SECRET`. The same secret is configured only in the
host app's ignored `.share.env` file.

## Data boundary and retention

- Shared: interim/final original text, translations, Decision Radar items, and
  evidence segment IDs created after sharing begins.
- Never shared: audio, API keys, provider settings, device details, or past
  sessions.
- Explicit stop clears relay text immediately.
- An inactive host expires after 15 minutes and every room has an 8-hour hard
  limit. Expiry is enforced before viewer or host access.
- Viewer routes are read-only. Room creation and event updates require separate
  bearer secrets.

## Workspace Auth Headers

OpenAI workspace sites can read the current user's email from
`oai-authenticated-user-email`.

SIWC-authenticated workspace sites may also receive
`oai-authenticated-user-full-name` when the user's SIWC profile has a non-empty
`name` claim. The full-name value is percent-encoded UTF-8 and is accompanied by
`oai-authenticated-user-full-name-encoding: percent-encoded-utf-8`.

Treat the full name as optional and fall back to email when it is absent:

```tsx
import { headers } from "next/headers";

export default async function Home() {
  const requestHeaders = await headers();
  const email = requestHeaders.get("oai-authenticated-user-email");
  const encodedFullName = requestHeaders.get("oai-authenticated-user-full-name");
  const fullName =
    encodedFullName &&
    requestHeaders.get("oai-authenticated-user-full-name-encoding") ===
      "percent-encoded-utf-8"
      ? decodeURIComponent(encodedFullName)
      : null;

  const displayName = fullName ?? email;
  // ...
}
```

## Optional Dispatch-Owned ChatGPT Sign-In

Import the ready-to-use helpers from `app/chatgpt-auth.ts` when the site needs
optional or required ChatGPT sign-in:

- Use `getChatGPTUser()` for optional signed-in UI.
- Use `requireChatGPTUser(returnTo)` for server-rendered pages that should send
  anonymous visitors through Sign in with ChatGPT.
- Use `chatGPTSignInPath(returnTo)` and `chatGPTSignOutPath(returnTo)` for
  browser links or actions.
- Pass a same-origin relative `returnTo` path for the destination after sign-in
  or sign-out. The helper validates and safely encodes it.
- Mark protected pages with `export const dynamic = "force-dynamic"` because
  they depend on per-request identity headers.

Dispatch owns `/signin-with-chatgpt`, `/signout-with-chatgpt`, `/callback`, the
OAuth cookies, and identity header injection. Do not implement app routes for
those reserved paths. Routes that do not import and call the helper remain
anonymous-compatible.

SIWC establishes identity only; it does not prove workspace membership. Use the
Sites hosting platform's access policy controls for workspace-wide restrictions,
or enforce explicit server-side membership or allowlist checks.

Use SIWC for account pages, user-specific dashboards, saved records, and write
actions tied to the current ChatGPT user. Leave public content anonymous.

## Useful commands

- `pnpm run dev`: start local development
- `pnpm run build`: verify the vinext build output
- `pnpm test`: build and verify server-rendered viewer pages
- `pnpm run db:generate`: generate D1 migrations after schema changes

## Learn More

- [vinext Documentation](https://github.com/cloudflare/vinext)
- [Drizzle D1 Guide](https://orm.drizzle.team/docs/get-started/d1-new)
