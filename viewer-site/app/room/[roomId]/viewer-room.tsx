"use client";

import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { SharedRadarItem, SharedSegment } from "../../../lib/relay";
import { getViewerSupabaseClient } from "../../../lib/supabase-browser";

type ViewerState = {
  capture_status: string;
  partial: { utterance_id: string; text: string; language: string; timestamp: string | null } | null;
  segments: SharedSegment[];
  radar: {
    status: string;
    revision: number;
    updated_at: string | null;
    queue_size: number;
    message: string | null;
    items: SharedRadarItem[];
  };
};

type RoomPayload = {
  status: string;
  revision: number;
  expires_at: string;
  presenter_online: boolean;
  retention_policy: string;
  state: ViewerState;
};

type Language = "ko" | "en";
type ViewMode = "both" | "translation";
type RadarTab = "core" | "decision" | "action" | "issues";
type AccessStage = "checking" | "signin" | "authenticated";
type AuthErrorCode = "" | "access" | "email_invalid" | "email_send" | "provider_unavailable" | "rate_limited";
type AuthOperation = "" | "continue" | "email" | "google";

const MAGIC_LINK_COOLDOWN_SECONDS = 60;
const MAGIC_LINK_COOLDOWN_STORAGE_PREFIX = "whykaigi:magic-link:sent-at:";

const copy = {
  ko: {
    live: "실시간 공유 중",
    reconnecting: "연결 다시 확인 중",
    ended: "공유가 종료되었습니다",
    unavailable: "회의방을 확인할 수 없습니다",
    captions: "실시간 자막",
    radar: "Decision Radar",
    interim: "임시 원문",
    waiting: "확정 자막을 기다리고 있습니다.",
    translationWaiting: "번역을 기다리는 중…",
    translationError: "번역을 표시하지 못했습니다. 원문은 계속 공유됩니다.",
    both: "원문 + 번역",
    translation: "번역만",
    privacy: "오디오·API 키·Provider 설정·과거 세션은 공유되지 않습니다.",
    retention: "공유 종료 시 중계 텍스트·신원·세션 데이터 삭제 · 진행자 로컬 입장 기록 최대 30일",
    decisions: "결정 사항",
    actions: "할 일",
    questions: "미해결 질문",
    confirmations: "확인 필요",
    core: "핵심",
    issues: "미해결",
    newItems: "개 새 항목",
    latest: "최신으로",
    noRadar: "아직 포착한 항목이 없습니다.",
    suggested: "제안",
    approved: "승인됨",
    assignee: "담당",
    due: "기한",
    evidence: "근거",
    evidenceUnavailable: "해당 근거는 현재 자막 표시 범위를 벗어났습니다.",
    presenterOffline: "진행자 연결 확인 중",
    radarDelayed: "Radar 분석이 지연 중이지만 자막은 계속 표시됩니다.",
    expired: "진행자가 공유를 종료했거나 보관 기간이 만료되었습니다.",
    accessTitle: "이메일 확인 후 입장",
    accessLead: "Google 계정 또는 이메일 로그인 링크로 본인 이메일을 확인하세요. 확인된 이메일과 이 방의 입장 기록만 진행자에게 표시됩니다.",
    signInGoogle: "Google로 계속하기",
    continueRoom: "이 방에 입장하기",
    orEmail: "또는 이메일로 확인",
    emailLabel: "이메일",
    emailPlaceholder: "name@example.com",
    sendMagicLink: "이메일 로그인 링크 받기",
    resendMagicLink: "로그인 링크 다시 보내기",
    sendingMagicLink: "로그인 링크 보내는 중…",
    magicLinkSent: "로그인 링크를 보냈습니다. 같은 브라우저와 기기에서 메일의 링크를 열면 방 입장을 계속할 수 있습니다.",
    useAnotherAccount: "다른 계정 사용하기",
    emailInvalid: "올바른 이메일 주소를 입력하세요.",
    emailSendError: "로그인 링크를 보내지 못했습니다. 잠시 후 다시 시도하세요.",
    authenticating: "계정 확인 중…",
    rateLimited: "로그인 요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
    providerUnavailable: "Supabase 로그인이 아직 설정되지 않았습니다. 진행자에게 알려주세요.",
    accessError: "확인된 이메일로 방에 입장하지 못했습니다. 잠시 후 다시 시도하세요.",
    accessPrivacy: "Supabase는 Google 또는 이메일 로그인 링크로 계정 소유 여부를 확인합니다. 중계 서버의 확인 이메일과 입장 세션은 공유 종료 시 삭제되며, 진행자는 보안 감사용 입장 기록을 로컬에 최대 30일 보관할 수 있습니다.",
    contentPrivacy: "회의 중계 텍스트와 중계 서버의 신원·세션 데이터는 공유 종료 시 삭제됩니다.",
    signOut: "나가기",
  },
  en: {
    live: "Live sharing",
    reconnecting: "Reconnecting",
    ended: "Sharing has ended",
    unavailable: "This meeting room is unavailable",
    captions: "Live captions",
    radar: "Decision Radar",
    interim: "Interim original",
    waiting: "Waiting for finalized captions.",
    translationWaiting: "Waiting for translation…",
    translationError: "Translation is unavailable. The original continues.",
    both: "Original + translation",
    translation: "Translation only",
    privacy: "Audio, API keys, provider settings, and past sessions are not shared.",
    retention: "Relay text, identity, and session data are deleted when sharing ends · Host-local access log up to 30 days",
    decisions: "Decisions",
    actions: "Action items",
    questions: "Open questions",
    confirmations: "Needs confirmation",
    core: "Key items",
    issues: "Open",
    newItems: "new items",
    latest: "Jump to latest",
    noRadar: "No evidence-linked items yet.",
    suggested: "Suggested",
    approved: "Approved",
    assignee: "Owner",
    due: "Due",
    evidence: "Evidence",
    evidenceUnavailable: "That evidence is outside the current caption window.",
    presenterOffline: "Checking presenter connection",
    radarDelayed: "Radar analysis is delayed. Captions continue.",
    expired: "The host ended sharing or the retention period expired.",
    accessTitle: "Continue with a verified email",
    accessLead: "Verify your email with Google or an email sign-in link. Only the verified email and this room's access event are shown to the host.",
    signInGoogle: "Continue with Google",
    continueRoom: "Continue to this room",
    orEmail: "Or verify by email",
    emailLabel: "Email",
    emailPlaceholder: "name@example.com",
    sendMagicLink: "Send email sign-in link",
    resendMagicLink: "Resend sign-in link",
    sendingMagicLink: "Sending sign-in link…",
    magicLinkSent: "We sent a sign-in link. Open it on this browser and device to continue into the room.",
    useAnotherAccount: "Use another account",
    emailInvalid: "Enter a valid email address.",
    emailSendError: "We could not send the sign-in link. Wait a moment and try again.",
    authenticating: "Checking account…",
    rateLimited: "Too many sign-in requests. Please wait and try again.",
    providerUnavailable: "Supabase sign-in is not configured yet. Contact the host.",
    accessError: "A verified email could not enter this room. Try again shortly.",
    accessPrivacy: "Supabase verifies account ownership through Google or an email sign-in link. The relay deletes verified identity and room-session data when sharing ends; the host may keep a local access audit for up to 30 days.",
    contentPrivacy: "Relayed meeting text, identity, and session data are deleted when sharing ends.",
    signOut: "Sign out",
  },
} as const;

const radarTabCategories: Record<RadarTab, SharedRadarItem["category"][]> = {
  core: ["decision", "action_item"],
  decision: ["decision"],
  action: ["action_item"],
  issues: ["open_question", "needs_confirmation"],
};

function tabsForRadarCategory(category: SharedRadarItem["category"]): RadarTab[] {
  if (category === "decision") return ["core", "decision"];
  if (category === "action_item") return ["core", "action"];
  return ["issues"];
}

function displayTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

type RoomAccessExchange = {
  code?: string;
  email?: string;
  ok: boolean;
  status: number;
};

async function exchangeRoomAccess(roomId: string, accessToken: string): Promise<RoomAccessExchange> {
  const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/supabase`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  const result = await response.json().catch(() => ({})) as {
    code?: string;
    email?: string;
  };
  return { ...result, ok: response.ok, status: response.status };
}

function scrubOAuthCallbackParams() {
  const url = new URL(window.location.href);
  ["code", "error", "error_code", "error_description"].forEach((key) => url.searchParams.delete(key));
  const cleanUrl = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState(window.history.state, "", cleanUrl);
}

function authErrorCodeFor(code: string): AuthErrorCode {
  const normalized = code.toLowerCase();
  if (normalized.includes("rate_limit") || normalized.includes("rate limit") || normalized.includes("too many requests")) {
    return "rate_limited";
  }
  if (normalized.includes("provider_disabled") || normalized.includes("email logins are disabled") || normalized === "supabase_auth_unavailable") {
    return "provider_unavailable";
  }
  return "access";
}

function emailAuthErrorCodeFor(code: string): AuthErrorCode {
  const shared = authErrorCodeFor(code);
  return shared === "access" ? "email_send" : shared;
}

function errorText(error: unknown) {
  if (!(error instanceof Error)) return "";
  const code = "code" in error && typeof error.code === "string" ? error.code : "";
  return `${code} ${error.message}`.trim();
}

function normalizedEmail(value: string) {
  return value.trim().toLowerCase();
}

function validEmail(value: string) {
  return value.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function roomRedirectUrl(roomId: string) {
  return new URL(`/room/${encodeURIComponent(roomId)}`, window.location.origin).toString();
}

function magicLinkCooldownKey(email: string) {
  return `${MAGIC_LINK_COOLDOWN_STORAGE_PREFIX}${email}`;
}

function readMagicLinkCooldown(email: string, now = Date.now()) {
  if (!email || typeof window === "undefined") return 0;
  try {
    const sentAt = Number(window.localStorage.getItem(magicLinkCooldownKey(email)));
    if (!Number.isFinite(sentAt) || sentAt <= 0) {
      window.localStorage.removeItem(magicLinkCooldownKey(email));
      return 0;
    }
    const remaining = Math.ceil((sentAt + MAGIC_LINK_COOLDOWN_SECONDS * 1_000 - now) / 1_000);
    if (remaining <= 0) {
      window.localStorage.removeItem(magicLinkCooldownKey(email));
      return 0;
    }
    return remaining;
  } catch {
    return 0;
  }
}

function startMagicLinkCooldown(email: string) {
  try {
    window.localStorage.setItem(magicLinkCooldownKey(email), String(Date.now()));
  } catch {
    // A blocked localStorage must not turn a successful Supabase request into an error.
  }
}

function magicLinkCooldownText(language: Language, seconds: number) {
  return language === "ko"
    ? `로그인 링크를 ${seconds}초 후에 다시 보낼 수 있습니다.`
    : `You can resend the sign-in link in ${seconds} seconds.`;
}

export function ViewerRoom({ roomId }: { roomId: string }) {
  const [payload, setPayload] = useState<RoomPayload | null>(null);
  const [connection, setConnection] = useState<"connecting" | "live" | "reconnecting" | "ended" | "missing">("connecting");
  const [language, setLanguage] = useState<Language>("ko");
  const [viewMode, setViewMode] = useState<ViewMode>("both");
  const [radarTab, setRadarTab] = useState<RadarTab>("core");
  const [radarUnread, setRadarUnread] = useState<Record<RadarTab, number>>({ core: 0, decision: 0, action: 0, issues: 0 });
  const [evidenceNotice, setEvidenceNotice] = useState("");
  const [accessStage, setAccessStage] = useState<AccessStage>("checking");
  const [authEmail, setAuthEmail] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [magicLinkSentTo, setMagicLinkSentTo] = useState("");
  const [magicLinkCooldownSeconds, setMagicLinkCooldownSeconds] = useState(0);
  const [authBusy, setAuthBusy] = useState(false);
  const [authOperation, setAuthOperation] = useState<AuthOperation>("");
  const [authError, setAuthError] = useState<AuthErrorCode>("");
  const [supabaseConfigured, setSupabaseConfigured] = useState(true);
  const [hasSupabaseSession, setHasSupabaseSession] = useState(false);
  const authRequestInFlightRef = useRef(false);
  const emailInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const radarScrollRef = useRef<HTMLDivElement>(null);
  const radarPinnedRef = useRef(true);
  const radarKnownIdsRef = useRef(new Set<string>());
  const radarInitializedRef = useRef(false);
  const lastRevision = useRef(-1);
  const labels = copy[language];
  const captionSegments = useMemo(
    () => [...(payload?.state.segments ?? [])].reverse(),
    [payload?.state.segments],
  );
  const radarItems = useMemo(() => payload?.state.radar.items ?? [], [payload?.state.radar.items]);

  useEffect(() => {
    const stored = window.localStorage.getItem("mlt-viewer-language");
    if (stored !== "ko" && stored !== "en") return;
    const timer = window.setTimeout(() => setLanguage(stored), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const email = normalizedEmail(emailInput);
    if (!validEmail(email)) {
      const timer = window.setTimeout(() => setMagicLinkCooldownSeconds(0), 0);
      return () => window.clearTimeout(timer);
    }

    const updateCooldown = () => setMagicLinkCooldownSeconds(readMagicLinkCooldown(email));
    updateCooldown();
    const timer = window.setInterval(updateCooldown, 1_000);
    return () => window.clearInterval(timer);
  }, [emailInput]);

  useEffect(() => {
    let cancelled = false;
    const checkAccess = async () => {
      const callbackUrl = new URL(window.location.href);
      const authCode = callbackUrl.searchParams.get("code");
      const hasOAuthError = callbackUrl.searchParams.has("error")
        || callbackUrl.searchParams.has("error_code")
        || callbackUrl.searchParams.has("error_description");
      const hasOAuthCallbackParams = Boolean(authCode || hasOAuthError);
      let scrubCallbackWhenDone = hasOAuthError;
      try {
        const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/status`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (cancelled) return;
        if (response.status === 410) {
          scrubCallbackWhenDone = hasOAuthCallbackParams;
          setConnection("ended");
          return;
        }
        if (response.status === 404) {
          scrubCallbackWhenDone = hasOAuthCallbackParams;
          setConnection("missing");
          return;
        }
        if (!response.ok) throw new Error("access_status_failed");
        const status = await response.json() as {
          authenticated?: boolean;
          email?: string | null;
          supabase_auth_configured?: boolean;
        };
        setSupabaseConfigured(status.supabase_auth_configured !== false);
        if (status.authenticated) {
          scrubCallbackWhenDone = hasOAuthCallbackParams;
          setAuthEmail(status.email ?? "");
          setAccessStage("authenticated");
          return;
        }
        if (status.supabase_auth_configured === false) {
          scrubCallbackWhenDone = hasOAuthCallbackParams;
          setAccessStage("signin");
          setAuthError("provider_unavailable");
          return;
        }

        if (hasOAuthError) {
          setAccessStage("signin");
          setAuthError("access");
          return;
        }

        const supabase = await getViewerSupabaseClient();
        if (!authCode) {
          const { data, error } = await supabase.auth.getSession();
          if (error) throw error;
          if (cancelled) return;
          setHasSupabaseSession(Boolean(data.session?.access_token));
          setAuthEmail(data.session?.user.email ?? "");
          setAccessStage("signin");
          return;
        }

        scrubCallbackWhenDone = true;
        const { data, error } = await supabase.auth.exchangeCodeForSession(authCode);
        let session = data.session;
        if (error || !session?.access_token) {
          const { data: current, error: sessionError } = await supabase.auth.getSession();
          if (sessionError || !current.session?.access_token) throw error ?? sessionError ?? new Error("supabase_auth_failed");
          session = current.session;
        }
        if (cancelled) return;
        setHasSupabaseSession(true);
        setAuthEmail(session.user.email ?? "");
        setAccessStage("signin");
        setConnection("connecting");
        return;
      } catch (error) {
        if (!cancelled) {
          setAccessStage("signin");
          setAuthError(authErrorCodeFor(errorText(error)));
        }
      } finally {
        if (scrubCallbackWhenDone) scrubOAuthCallbackParams();
      }
    };
    void checkAccess();
    return () => { cancelled = true; };
  }, [roomId]);

  useEffect(() => {
    if (accessStage !== "authenticated") return;
    let cancelled = false;
    let terminal = false;
    let timer = 0;
    const poll = async () => {
      try {
        const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (cancelled) return;
        if (response.status === 410) {
          terminal = true;
          setPayload(null);
          setConnection("ended");
          return;
        }
        if (response.status === 404) {
          terminal = true;
          setPayload(null);
          setConnection("missing");
          return;
        }
        if (response.status === 401) {
          terminal = true;
          setPayload(null);
          setAccessStage("signin");
          setAuthError("");
          return;
        }
        if (!response.ok) throw new Error("room_fetch_failed");
        const next = (await response.json()) as RoomPayload;
        setPayload(next);
        setConnection(next.presenter_online ? "live" : "reconnecting");
      } catch {
        if (!cancelled) setConnection((current) => current === "connecting" ? "reconnecting" : current);
      } finally {
        if (!cancelled && !terminal) {
          timer = window.setTimeout(poll, document.hidden ? 1_500 : 450);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [roomId, accessStage]);

  const authErrorMessages: Record<AuthErrorCode, string> = {
    "": "",
    access: labels.accessError,
    email_invalid: labels.emailInvalid,
    email_send: labels.emailSendError,
    provider_unavailable: labels.providerUnavailable,
    rate_limited: labels.rateLimited,
  };
  const authErrorMessage = authErrorMessages[authError];

  const continueToRoom = async () => {
    if (authRequestInFlightRef.current) return;
    authRequestInFlightRef.current = true;
    setAuthBusy(true);
    setAuthOperation("continue");
    setAuthError("");
    try {
      const supabase = await getViewerSupabaseClient();
      const { data, error: sessionError } = await supabase.auth.getSession();
      if (sessionError) throw sessionError;
      const accessToken = data.session?.access_token;
      if (!accessToken) {
        setHasSupabaseSession(false);
        setAuthEmail("");
        throw new Error("verified_identity_required");
      }

      const exchange = await exchangeRoomAccess(roomId, accessToken);
      if (exchange.status === 410) {
        setConnection("ended");
        return;
      }
      if (exchange.status === 404) {
        setConnection("missing");
        return;
      }
      if (!exchange.ok) {
        if (exchange.code === "verified_identity_required" || exchange.code === "google_identity_required") {
          await supabase.auth.signOut({ scope: "local" }).catch(() => undefined);
          setHasSupabaseSession(false);
          setAuthEmail("");
        }
        throw new Error(exchange.code || "supabase_auth_failed");
      }
      setHasSupabaseSession(true);
      setAuthEmail(exchange.email ?? data.session?.user.email ?? "");
      setAccessStage("authenticated");
      setConnection("connecting");
    } catch (error) {
      setAuthError(authErrorCodeFor(errorText(error)));
    } finally {
      authRequestInFlightRef.current = false;
      setAuthBusy(false);
      setAuthOperation("");
    }
  };

  const signInWithGoogle = async () => {
    if (authRequestInFlightRef.current) return;
    authRequestInFlightRef.current = true;
    setAuthBusy(true);
    setAuthOperation("google");
    setAuthError("");
    let redirectStarted = false;
    try {
      const supabase = await getViewerSupabaseClient();
      const { data, error: sessionError } = await supabase.auth.getSession();
      if (sessionError) throw sessionError;
      if (data.session?.access_token) {
        setHasSupabaseSession(true);
        setAuthEmail(data.session.user.email ?? "");
        return;
      }

      const redirectTo = roomRedirectUrl(roomId);
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo },
      });
      if (error) throw error;
      redirectStarted = true;
    } catch (error) {
      setAuthError(authErrorCodeFor(errorText(error)));
    } finally {
      if (!redirectStarted) {
        authRequestInFlightRef.current = false;
        setAuthBusy(false);
        setAuthOperation("");
      }
    }
  };

  const sendMagicLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (authRequestInFlightRef.current) return;
    const email = normalizedEmail(emailInput);
    if (!validEmail(email)) {
      setAuthError("email_invalid");
      emailInputRef.current?.focus();
      return;
    }
    const cooldownSeconds = readMagicLinkCooldown(email);
    if (cooldownSeconds > 0) {
      setMagicLinkCooldownSeconds(cooldownSeconds);
      return;
    }

    authRequestInFlightRef.current = true;
    setAuthBusy(true);
    setAuthOperation("email");
    setAuthError("");
    setEmailInput(email);
    try {
      const supabase = await getViewerSupabaseClient();
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: roomRedirectUrl(roomId),
          shouldCreateUser: true,
        },
      });
      if (error) throw error;
      startMagicLinkCooldown(email);
      setMagicLinkCooldownSeconds(MAGIC_LINK_COOLDOWN_SECONDS);
      setMagicLinkSentTo(email);
    } catch (error) {
      setAuthError(emailAuthErrorCodeFor(errorText(error)));
    } finally {
      authRequestInFlightRef.current = false;
      setAuthBusy(false);
      setAuthOperation("");
    }
  };

  const signOut = async () => {
    await fetch(`/api/rooms/${encodeURIComponent(roomId)}/auth/logout`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }).catch(() => undefined);
    const supabase = await getViewerSupabaseClient().catch(() => null);
    await supabase?.auth.signOut({ scope: "local" }).catch(() => undefined);
    setPayload(null);
    setAuthEmail("");
    setMagicLinkSentTo("");
    setHasSupabaseSession(false);
    setAuthError("");
    setAccessStage("signin");
    setConnection("connecting");
  };

  useEffect(() => {
    if (!payload || payload.revision === lastRevision.current) return;
    lastRevision.current = payload.revision;
    const container = scrollRef.current;
    if (container) container.scrollTo({ top: 0, behavior: "smooth" });
  }, [payload]);

  const activeRadarItems = useMemo(
    () => radarItems.filter((item) => item.lifecycle_status === "active"),
    [radarItems],
  );
  const radarHistoryItems = useMemo(
    () => radarItems.filter((item) => item.lifecycle_status !== "active").slice().reverse(),
    [radarItems],
  );
  const radarCounts = useMemo(() => ({
    core: activeRadarItems.filter((item) => radarTabCategories.core.includes(item.category)).length,
    decision: activeRadarItems.filter((item) => item.category === "decision").length,
    action: activeRadarItems.filter((item) => item.category === "action_item").length,
    issues: activeRadarItems.filter((item) => radarTabCategories.issues.includes(item.category)).length,
  }), [activeRadarItems]);

  const visibleRadarItems = useMemo(
    () => activeRadarItems.filter((item) => radarTabCategories[radarTab].includes(item.category)),
    [activeRadarItems, radarTab],
  );

  useEffect(() => {
    const nextIds = new Set(activeRadarItems.map((item) => item.item_id));
    if (!radarInitializedRef.current) {
      radarKnownIdsRef.current = nextIds;
      radarInitializedRef.current = true;
    } else {
      const added = activeRadarItems.filter((item) => !radarKnownIdsRef.current.has(item.item_id));
      if (added.length) {
        setRadarUnread((current) => {
          const next = { ...current };
          added.forEach((item) => {
            tabsForRadarCategory(item.category).forEach((tab) => {
              if (tab !== radarTab || !radarPinnedRef.current) next[tab] += 1;
            });
          });
          return next;
        });
      }
      radarKnownIdsRef.current = nextIds;
    }
    if (radarPinnedRef.current) {
      window.requestAnimationFrame(() => {
        const container = radarScrollRef.current;
        if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      });
    }
  }, [activeRadarItems, radarTab]);

  const chooseLanguage = (next: Language) => {
    setLanguage(next);
    window.localStorage.setItem("mlt-viewer-language", next);
  };

  const chooseRadarTab = (next: RadarTab) => {
    setRadarTab(next);
    setRadarUnread((current) => ({ ...current, [next]: 0 }));
    radarPinnedRef.current = true;
    window.requestAnimationFrame(() => {
      const container = radarScrollRef.current;
      if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    });
  };

  const handleRadarScroll = () => {
    const container = radarScrollRef.current;
    if (!container) return;
    const atLatest = container.scrollHeight - container.scrollTop - container.clientHeight <= 36;
    radarPinnedRef.current = atLatest;
    if (atLatest && radarUnread[radarTab]) {
      setRadarUnread((current) => ({ ...current, [radarTab]: 0 }));
    }
  };

  const jumpToLatestRadar = () => {
    radarPinnedRef.current = true;
    setRadarUnread((current) => ({ ...current, [radarTab]: 0 }));
    const container = radarScrollRef.current;
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  };

  const jumpToEvidence = (segmentId: string) => {
    const target = document.getElementById(`segment-${segmentId}`);
    if (!target) {
      setEvidenceNotice(labels.evidenceUnavailable);
      return;
    }
    setEvidenceNotice("");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("evidence-highlight");
    window.requestAnimationFrame(() => target.classList.add("evidence-highlight"));
  };

  const connectionLabel = connection === "live"
    ? labels.live
    : connection === "ended"
      ? labels.ended
      : connection === "missing"
        ? labels.unavailable
        : labels.reconnecting;

  if (connection === "ended" || connection === "missing") {
    return (
      <main className="viewer-ended" data-testid="room-ended">
        <div className="ended-mark" aria-hidden="true">×</div>
        <p className="viewer-eyebrow">WHYKAIGI</p>
        <h1>{connectionLabel}</h1>
        <p>{labels.expired}</p>
        <div className="privacy-chip">{labels.retention}</div>
      </main>
    );
  }

  if (accessStage !== "authenticated") {
    return (
      <main className="viewer-access" data-testid="viewer-access-gate">
        <section className="access-card" aria-busy={authBusy}>
          <header className="access-header">
            <div className="viewer-brand">
              <span className="brand-signal whykaigi-mark" aria-hidden="true" />
              <div><p>WHYKAIGI</p><h1>Secure shared meeting</h1></div>
            </div>
            <div className="language-toggle" aria-label="Language">
              <button type="button" className={language === "ko" ? "active" : ""} onClick={() => chooseLanguage("ko")}>한국어</button>
              <button type="button" className={language === "en" ? "active" : ""} onClick={() => chooseLanguage("en")}>English</button>
            </div>
          </header>
          <div className="access-lock" aria-hidden="true">✦</div>
          <p className="viewer-eyebrow">SUPABASE · VERIFIED EMAIL</p>
          <h2>{labels.accessTitle}</h2>
          <p className="access-lead">{labels.accessLead}</p>
          {accessStage === "checking" ? (
            <div className="access-checking"><i />{language === "ko" ? "초대 링크 확인 중…" : "Checking invite…"}</div>
          ) : hasSupabaseSession ? (
            <div className="access-form">
              {authEmail && <div className="access-email-row"><span>{authEmail}</span></div>}
              <button
                className="access-continue"
                type="button"
                disabled={authBusy || !supabaseConfigured}
                onClick={() => void continueToRoom()}
              >
                {authOperation === "continue" ? labels.authenticating : labels.continueRoom}
              </button>
              <button
                className="access-secondary"
                type="button"
                disabled={authBusy}
                onClick={() => void signOut()}
              >
                {labels.useAnotherAccount}
              </button>
            </div>
          ) : (
            <form className="access-form" noValidate onSubmit={(event) => void sendMagicLink(event)}>
              <button
                className="access-google"
                type="button"
                disabled={authBusy || !supabaseConfigured}
                onClick={() => void signInWithGoogle()}
              >
                <span aria-hidden="true">G</span>
                {authOperation === "google" ? labels.authenticating : labels.signInGoogle}
              </button>
              <div className="access-divider" aria-hidden="true"><span>{labels.orEmail}</span></div>
              <label htmlFor="viewer-access-email">{labels.emailLabel}</label>
              <input
                ref={emailInputRef}
                id="viewer-access-email"
                type="email"
                inputMode="email"
                autoComplete="email"
                maxLength={254}
                value={emailInput}
                placeholder={labels.emailPlaceholder}
                aria-invalid={authError === "email_invalid"}
                aria-describedby={[
                  magicLinkSentTo || authErrorMessage ? "viewer-auth-feedback" : "",
                  magicLinkCooldownSeconds > 0 ? "viewer-magic-link-cooldown" : "",
                ].filter(Boolean).join(" ") || undefined}
                disabled={authBusy || !supabaseConfigured}
                onChange={(event) => {
                  const next = event.target.value;
                  setEmailInput(next);
                  if (authError === "email_invalid" || authError === "email_send") setAuthError("");
                  if (magicLinkSentTo && normalizedEmail(next) !== magicLinkSentTo) setMagicLinkSentTo("");
                }}
              />
              <button
                className="access-email-submit"
                type="submit"
                disabled={authBusy || !supabaseConfigured || !emailInput.trim() || magicLinkCooldownSeconds > 0}
              >
                {authOperation === "email"
                  ? labels.sendingMagicLink
                  : magicLinkCooldownSeconds > 0
                    ? magicLinkCooldownText(language, magicLinkCooldownSeconds)
                    : magicLinkSentTo
                    ? labels.resendMagicLink
                    : labels.sendMagicLink}
              </button>
              {magicLinkCooldownSeconds > 0 && (
                <p className="access-cooldown" id="viewer-magic-link-cooldown">
                  {magicLinkCooldownText(language, magicLinkCooldownSeconds)}
                </p>
              )}
            </form>
          )}
          {magicLinkSentTo && !authErrorMessage && (
            <p className="access-message" id="viewer-auth-feedback" role="status" aria-live="polite">
              <strong>{magicLinkSentTo}</strong><span>{labels.magicLinkSent}</span>
            </p>
          )}
          {authErrorMessage && <p className="access-error" id="viewer-auth-feedback" role="alert">{authErrorMessage}</p>}
          <aside className="access-privacy"><strong>{labels.contentPrivacy}</strong><span>{labels.accessPrivacy}</span></aside>
        </section>
      </main>
    );
  }

  return (
    <main className="viewer-shell" data-testid="viewer-room">
      <header className="viewer-header">
        <div className="viewer-brand">
          <span className="brand-signal whykaigi-mark" aria-hidden="true" />
          <div><p>WHYKAIGI</p><h1>Shared meeting view</h1></div>
        </div>
        <div className="viewer-header-actions">
          <div className="language-toggle" aria-label="Language">
            <button className={language === "ko" ? "active" : ""} onClick={() => chooseLanguage("ko")}>한국어</button>
            <button className={language === "en" ? "active" : ""} onClick={() => chooseLanguage("en")}>English</button>
          </div>
          {authEmail && <span className="viewer-identity" title={authEmail}>{authEmail}</span>}
          <button className="viewer-sign-out" type="button" onClick={() => void signOut()}>{labels.signOut}</button>
          <span className={`connection-pill ${connection}`}><i />{connectionLabel}</span>
        </div>
      </header>

      <aside className="privacy-strip">
        <span>{labels.privacy}</span>
        <strong>{labels.retention}</strong>
      </aside>

      <div className="viewer-grid">
        <section className="viewer-panel caption-viewer" aria-labelledby="captions-title">
          <div className="viewer-section-heading">
            <div><p>LIVE · CAPTIONS</p><h2 id="captions-title">{labels.captions}</h2></div>
            <div className="view-mode" aria-label="Caption view">
              <button className={viewMode === "both" ? "active" : ""} onClick={() => setViewMode("both")}>{labels.both}</button>
              <button className={viewMode === "translation" ? "active" : ""} onClick={() => setViewMode("translation")}>{labels.translation}</button>
            </div>
          </div>

          <div className={`viewer-partial ${payload?.state.partial ? "active" : ""}`}>
            <div><span><i />{labels.interim}</span><em>{payload?.state.partial?.language?.toUpperCase() ?? "—"}</em></div>
            <p>{payload?.state.partial?.text ?? labels.waiting}</p>
          </div>

          <div className="viewer-transcript-scroll" ref={scrollRef}>
            {captionSegments.length === 0 ? (
              <div className="viewer-empty"><span className="empty-wave"><i /><i /><i /><i /><i /></span><p>{labels.waiting}</p></div>
            ) : (
              <ol className="viewer-transcripts">
                {captionSegments.map((segment) => (
                  <li key={segment.segment_id} id={`segment-${segment.segment_id}`} className="viewer-segment">
                    <div className="segment-meta"><time>{displayTime(segment.ended_at ?? segment.timestamp)}</time><span>{segment.language.toUpperCase()}</span></div>
                    {viewMode === "both" && <p className="viewer-original">{segment.original_text}</p>}
                    <div className={`viewer-translation ${segment.translation_status}`}>
                      <small>{segment.translation_status === "success" ? "TRANSLATION" : segment.translation_status.toUpperCase()}</small>
                      <p>{segment.translated_text || (segment.translation_status === "error" ? labels.translationError : labels.translationWaiting)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <section className="viewer-panel radar-viewer" aria-labelledby="radar-title">
          <div className="viewer-section-heading">
            <div><p>LIVE · EVIDENCE-LINKED</p><h2 id="radar-title">{labels.radar}</h2></div>
            <span className={`radar-pill ${payload?.state.radar.status ?? "disabled"}`}>{payload?.state.radar.status ?? "—"}</span>
          </div>
          {connection === "reconnecting" && <p className="radar-advisory">{labels.presenterOffline}</p>}
          {payload?.state.radar.status === "error" && <p className="radar-advisory danger">{labels.radarDelayed}</p>}
          {evidenceNotice && <p className="radar-advisory">{evidenceNotice}</p>}
          <nav className="radar-tabs" aria-label="Radar views">
            {(["core", "decision", "action", "issues"] as RadarTab[]).map((tab) => {
              const title = tab === "core" ? labels.core : tab === "decision" ? labels.decisions : tab === "action" ? labels.actions : labels.issues;
              return <button key={tab} className={radarTab === tab ? "active" : ""} data-unread={radarUnread[tab] > 0} onClick={() => chooseRadarTab(tab)}><span>{title}</span><strong>{radarCounts[tab]}</strong><i aria-hidden="true" /></button>;
            })}
          </nav>
          {radarUnread[radarTab] > 0 && <button className="radar-latest" onClick={jumpToLatestRadar}>{radarUnread[radarTab]} {labels.newItems} · {labels.latest}</button>}
          <div className="radar-scroll" ref={radarScrollRef} onScroll={handleRadarScroll}>
            {visibleRadarItems.length === 0 ? (
              <div className="radar-empty"><span>⌁</span><p>{labels.noRadar}</p></div>
            ) : visibleRadarItems.map((item) => {
              const categoryTitle = item.category === "decision" ? labels.decisions : item.category === "action_item" ? labels.actions : item.category === "open_question" ? labels.questions : labels.confirmations;
              return <article className="radar-item" key={item.item_id}>
                <div className="radar-item-top"><span>{item.review_status === "approved" ? labels.approved : labels.suggested}</span><em>{categoryTitle}</em></div>
                <p>{item.text}</p>
                {(item.assignee || item.due_date) && <dl>
                  {item.assignee && <div><dt>{labels.assignee}</dt><dd>{item.assignee}</dd></div>}
                  {item.due_date && <div><dt>{labels.due}</dt><dd>{item.due_date}</dd></div>}
                </dl>}
                <div className="evidence-links">
                  {item.evidence_segment_ids.map((segmentId, index) => <button key={segmentId} onClick={() => jumpToEvidence(segmentId)}>{labels.evidence} {index + 1}</button>)}
                </div>
              </article>;
            })}
            {radarHistoryItems.length > 0 && <details className="radar-history">
              <summary>{language === "ko" ? "변경 기록" : "Change history"} <strong>{radarHistoryItems.length}</strong></summary>
              {radarHistoryItems.map((item) => <article className="radar-item historical" key={item.item_id}>
                <div className="radar-item-top"><span>{language === "ko" ? ({ superseded: "대체됨", resolved: "해결됨", retracted: "철회됨" }[item.lifecycle_status] ?? "변경됨") : item.lifecycle_status}</span></div>
                <p>{item.text}</p>
                {item.lifecycle_reason && <small>{item.lifecycle_reason}</small>}
                <div className="evidence-links">
                  {item.evidence_segment_ids.map((segmentId, index) => <button key={segmentId} onClick={() => jumpToEvidence(segmentId)}>{labels.evidence} {index + 1}</button>)}
                </div>
              </article>)}
            </details>}
          </div>
        </section>
      </div>
    </main>
  );
}
