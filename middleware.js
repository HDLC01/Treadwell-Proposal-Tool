// Vercel Edge Middleware — proxies /api/* to the laptop's ngrok tunnel
// and injects `ngrok-skip-browser-warning` so the free-tier interstitial
// HTML doesn't break our JSON responses.
//
// When ngrok URL changes, update NGROK_BASE and redeploy.

const NGROK_BASE = "https://guidebooky-gideon-pellucid.ngrok-free.dev";

export const config = {
  matcher: "/api/:path*",
};

export default async function middleware(request) {
  const url = new URL(request.url);
  const target = NGROK_BASE + url.pathname + url.search;

  // Clone request headers, drop hop-by-hop ones, add ngrok bypass.
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

  // Strip headers that the edge can't pass through unchanged.
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
