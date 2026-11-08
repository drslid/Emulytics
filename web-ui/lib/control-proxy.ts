const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const identifier = "[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}";
const reads = new RegExp(`^(auth/(me|enrollment|enrollment/qr)|devices|workflows|workflows/${identifier}/versions/[0-9]+|runs|runs/${UUID}(/events|/diagnosis)?|console/(summary|fleet|fleet/(groups(/${UUID})?|capacity)|dashboard|emulators|account/(profile|security|api-keys|chatgpt|two-factor/enrollment(/qr)?)|devices/${identifier}/screen|monitor(/stream)?|logs|users(/${UUID})?|recipes|schedules|executions/${UUID}/(captures/${identifier}|screen)))$`);
const userPath = `console/users/${UUID}`;
const recipePath = `console/recipes/${UUID}`;
const schedulePath = `console/schedules/${UUID}`;
const changes = {
  POST: new RegExp(`^(auth/(login|change-password|verify|recovery|logout)|devices|runs|runs/${UUID}/(cancel|retry)|console/(fleet/(groups|bulk)|emulators|emulators/${identifier}/(configuration|start|prepare|stop)|applications|users|recipes|recipes/(from-workflow|generate)|schedules|schedules/preview|account/(api-keys|password|recovery-codes|chatgpt/(login|cancel)|two-factor/(start|confirm)))|${userPath}/(reset-password|reset-2fa|revoke-sessions|force-password-change)|${recipePath}/publish)$`),
  PATCH: new RegExp(`^(${userPath}|${recipePath}|${schedulePath}|console/account/profile|console/fleet/groups/${UUID})$`),
  DELETE: new RegExp(`^(workflows/${identifier}/versions/[0-9]+|${schedulePath}|console/fleet/groups/${UUID}|console/account/(api-keys/${UUID}|chatgpt|two-factor/enrollment))$`)
};

export function sessionCookies(raw: string | null): string {
  return (raw ?? "").split(";").map((part) => part.trim()).filter((part) =>
    /^(emulytix_session|emulytix_challenge)=[A-Za-z0-9_.~-]{1,512}$/.test(part)
  ).join("; ");
}

function error(status: number, detail: string): Response {
  return Response.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}

export async function proxyControl(request: Request, segments: string[], fetcher = fetch): Promise<Response> {
  const endpoint = segments.join("/");
  const allowed = request.method === "GET" ? reads.test(endpoint) : changes[request.method as keyof typeof changes]?.test(endpoint);
  if (!allowed || segments.some((part) => !part || part.includes("/"))) return error(404, "Route indisponible.");
  const goBase = request.method === "GET" && (endpoint === "console/summary" || endpoint === "console/fleet" || endpoint === "console/dashboard")
    ? process.env.EMULYTIX_GO_API_INTERNAL_URL : undefined;
  const base = goBase || process.env.EMULYTIX_API_INTERNAL_URL;
  const origin = process.env.EMULYTIX_PUBLIC_ORIGIN;
  if (!base || !origin) return error(503, "La console n’est pas encore configurée.");
  const headers = new Headers({ Accept: "application/json", Cookie: sessionCookies(request.headers.get("cookie")) });
  let body: Uint8Array<ArrayBuffer> | undefined;
  const apkUpload = request.method === "POST" && endpoint === "console/applications";
  if (request.method !== "GET") {
    if (request.headers.get("origin") !== origin || request.headers.get("X-Emulytix-Client") !== "console") {
      return error(403, "Cette demande doit venir de la console.");
    }
    const contentType = request.headers.get("content-type") ?? "";
    if (contentType.split(";")[0].trim() !== (apkUpload ? "multipart/form-data" : "application/json")) {
      return error(415, "Une requête JSON est requise.");
    }
    headers.set("Origin", origin);
    headers.set("X-Emulytix-Client", "console");
    headers.set("Content-Type", apkUpload ? contentType : "application/json");
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > (apkUpload ? 128 * 1024 * 1024 + 65_536 : 65_536)) {
          await reader.cancel();
          return error(413, "La demande est trop volumineuse.");
        }
        chunks.push(value);
      }
    }
    body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  const search = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["limit", "offset", "after", "q", "category", "severity", "role", "active", "two_factor", "onboarding", "window"]) {
    const value = search.get(key);
    if (value !== null) query.set(key, value);
  }
  const timezone = endpoint === "console/dashboard" ? search.get("timezone") : null;
  if (timezone !== null) query.set("timezone", timezone);
  try {
    const streaming = endpoint === "console/monitor/stream";
    const controller = new AbortController();
    const timer = streaming ? setTimeout(() => controller.abort(), 15_000) : undefined;
    let upstream: Response;
    try { upstream = await fetcher(`${base.replace(/\/$/, "")}/${endpoint}?${query}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: streaming ? AbortSignal.any([request.signal, controller.signal]) : AbortSignal.timeout(endpoint === "console/recipes/generate" ? 100_000 : apkUpload || endpoint === "console/fleet/bulk" ? 60_000 : 15_000)
    }); } finally { if (timer) clearTimeout(timer); }
    const responseHeaders = new Headers({
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"
    });
    if (goBase && upstream.headers.get("X-Emulytix-Backend") === "go") responseHeaders.set("X-Emulytix-Backend", "go");
    for (const cookie of upstream.headers.getSetCookie()) {
      if (/^(emulytix_session|emulytix_challenge)=/.test(cookie)) responseHeaders.append("Set-Cookie", cookie);
    }
    if (streaming) responseHeaders.set("X-Accel-Buffering", "no");
    if (/^console\/(?:devices\/[^/]+|executions\/[0-9a-fA-F-]{36})\/screen$/.test(endpoint)) {
      for (const name of ["X-Screen-Captured-At", "X-Screen-Age", "X-Screen-Frame-Id"]) {
        const value = upstream.headers.get(name);
        if (value) responseHeaders.set(name, value);
      }
    }
    const retry = upstream.headers.get("retry-after");
    if (retry) responseHeaders.set("Retry-After", retry);
    if (upstream.status >= 500) return error(503, "Le service est indisponible. Réessaie dans un instant.");
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return error(503, "Impossible de joindre le service. Réessaie dans un instant.");
  }
}
