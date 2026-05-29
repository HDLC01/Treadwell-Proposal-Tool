// Vercel Edge function — proxies /api/* to the laptop's ngrok tunnel
// while injecting `ngrok-skip-browser-warning` so ngrok doesn't serve
// its browser interstitial HTML page on free-tier tunnels.
//
// When ngrok URL changes, update NGROK_BASE below + redeploy.

export const config = { runtime: "edge" };

const NGROK_BASE = "https://guidebooky-gideon-pellucid.ngrok-free.dev";

export default async function handler(request) {
  const url = new URL(request.url);
  const target = NGROK_BASE + url.pathname + url.search;

  // Forward most headers but rewrite host + add ngrok skip header.
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k === "host" || k === "connection" || k === "content-length") return;
    headers.set(key, value);
  });
  headers.set("ngrok-skip-browser-warning", "true");

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }

  const upstream = await fetch(target, init);

  // Strip headers that Vercel's edge can't forward as-is.
  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k === "content-encoding" || k === "transfer-encoding" || k === "content-length") return;
    respHeaders.set(key, value);
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}
