import { jsonResponse } from "../../../../../../lib/relay";

// Email OTP was replaced by verified Supabase Google identity. Keep the old
// endpoint fail-closed so stale clients cannot create an alternate room session
// when legacy Resend variables still exist in a local or rolled-back runtime.
export async function POST() {
  return jsonResponse(
    { code: "email_otp_removed" },
    410,
    { "Cache-Control": "no-store" },
  );
}
