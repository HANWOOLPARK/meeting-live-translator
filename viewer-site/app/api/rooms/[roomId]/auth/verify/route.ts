import { jsonResponse } from "../../../../../../lib/relay";

// Verification codes no longer grant Viewer sessions. This explicit tombstone
// prevents legacy clients or leftover environment variables from bypassing the
// Supabase Google exchange route.
export async function POST() {
  return jsonResponse(
    { code: "email_otp_removed" },
    410,
    { "Cache-Control": "no-store" },
  );
}
