"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

type PublicConfig = {
  configured: boolean;
  url?: string;
  publishable_key?: string;
};

let clientPromise: Promise<SupabaseClient> | null = null;

export function getViewerSupabaseClient() {
  if (clientPromise) return clientPromise;
  clientPromise = fetch("/api/auth/config", {
    cache: "no-store",
    headers: { Accept: "application/json" },
  })
    .then(async (response) => {
      const config = await response.json().catch(() => ({})) as PublicConfig;
      if (!response.ok || !config.configured || !config.url || !config.publishable_key) {
        throw new Error("supabase_auth_unavailable");
      }
      return createClient(config.url, config.publishable_key, {
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: false,
          flowType: "pkce",
          persistSession: true,
          storageKey: "whykaigi-viewer-auth",
        },
      });
    })
    .catch((error) => {
      clientPromise = null;
      throw error;
    });
  return clientPromise;
}
