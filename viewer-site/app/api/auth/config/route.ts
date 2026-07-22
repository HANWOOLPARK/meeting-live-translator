import { jsonResponse } from "../../../../lib/relay";
import {
  supabaseAuthConfigured,
  supabasePublicConfig,
} from "../../../../lib/supabase-auth";

export async function GET() {
  const config = supabaseAuthConfigured() ? supabasePublicConfig() : null;
  return jsonResponse({
    configured: Boolean(config),
    url: config?.url ?? null,
    publishable_key: config?.publishableKey ?? null,
    provider: config ? "supabase" : null,
    providers: config ? ["google", "email"] : [],
  }, config ? 200 : 503, { "Cache-Control": "no-store" });
}
