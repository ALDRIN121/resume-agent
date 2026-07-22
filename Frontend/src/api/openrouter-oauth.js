// OpenRouter OAuth (PKCE) — browser side.
//
// Flow: generate a code_verifier + S256 challenge, redirect the user to
// OpenRouter's /auth page, and on return exchange the ?code= (via the backend)
// for a user-owned API key. The verifier is kept in sessionStorage between the
// redirect and the callback — standard SPA PKCE.

const VERIFIER_KEY = "or.pkce.verifier";
const PENDING_KEY = "or.pkce.pending";

function base64url(bytes) {
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256Challenge(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

// Kick off the redirect to OpenRouter. Never returns (navigates away).
export async function startOpenRouterSignIn() {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = await sha256Challenge(verifier);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(PENDING_KEY, "1");

  // OpenRouter redirects back to callback_url with ?code= appended.
  const callbackUrl = window.location.origin + window.location.pathname;
  const authUrl = new URL("https://openrouter.ai/auth");
  authUrl.searchParams.set("callback_url", callbackUrl);
  authUrl.searchParams.set("code_challenge", challenge);
  authUrl.searchParams.set("code_challenge_method", "S256");
  window.location.href = authUrl.toString();
}

// If we've just returned from OpenRouter, return {code, codeVerifier} and clean
// up (verifier + the ?code= query param). Otherwise null.
export function consumeOpenRouterCallback() {
  if (sessionStorage.getItem(PENDING_KEY) !== "1") return null;
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const verifier = sessionStorage.getItem(VERIFIER_KEY);

  sessionStorage.removeItem(PENDING_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  if (!code || !verifier) return null;

  // Strip ?code= (and any siblings OpenRouter added) from the visible URL.
  params.delete("code");
  const clean = window.location.pathname + (params.toString() ? `?${params}` : "");
  window.history.replaceState({}, "", clean);

  return { code, codeVerifier: verifier };
}
