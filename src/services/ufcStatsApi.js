/**
 * Browser client for the /api/ufcstats Vercel proxy.
 *
 * Returns null silently when the proxy isn't running (local dev without
 * `vercel dev`) so the app degrades gracefully to ESPN-only data.
 */

export async function fetchUFCStats(fighterName) {
  if (!fighterName) return null;
  try {
    const params = new URLSearchParams({ name: fighterName });
    const res    = await fetch(`/api/ufcstats?${params}`, {
      signal: AbortSignal.timeout(6000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.error ? null : data;
  } catch {
    // Proxy not available (local dev without vercel dev) — silent skip
    return null;
  }
}
