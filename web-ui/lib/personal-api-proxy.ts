// The external API accepts only a personal Bearer; console cookies never cross this boundary.
const uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const identifier = '[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}';
const reads = new RegExp(`^(capabilities|devices|workflows|workflows/${identifier}/versions/[0-9]+|runs|runs/${uuid}(/events)?)$`);
const writes = new RegExp(`^(workflows|runs|runs/${uuid}/cancel)$`);

function failure(status: number, detail: string): Response {
  return Response.json({ detail }, { status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
}

export async function proxyPersonalAPI(request: Request, segments: string[], fetcher = fetch): Promise<Response> {
  const endpoint = segments.join('/');
  if (segments.some((part) => !part || part.includes('/')) || !(request.method === 'GET' ? reads.test(endpoint) : request.method === 'POST' && writes.test(endpoint)))
    return failure(404, 'Route indisponible.');
  const base = process.env.EMULYTIX_API_INTERNAL_URL;
  const origin = process.env.EMULYTIX_PUBLIC_ORIGIN;
  if (!base || !origin) return failure(503, 'Service indisponible.');
  if (request.headers.has('origin') && request.headers.get('origin') !== origin) return failure(403, 'Origine refusée.');
  const authorization = request.headers.get('authorization') ?? '';
  if (!/^Bearer emk_[A-Za-z0-9_-]{43}$/i.test(authorization)) return failure(401, 'Clé API personnelle requise.');
  const headers = new Headers({ Authorization: authorization, Accept: 'application/json' });
  const incomingOrigin = request.headers.get('origin');
  if (incomingOrigin) headers.set('Origin', incomingOrigin);
  let body: Uint8Array<ArrayBuffer> | undefined;
  if (request.method === 'POST') {
    if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') return failure(415, 'Requête JSON requise.');
    headers.set('Content-Type', 'application/json');
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 65_536) { await reader.cancel(); return failure(413, 'Demande trop volumineuse.'); }
      chunks.push(value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  const inputQuery = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const name of ['limit', 'offset', 'after']) {
    const value = inputQuery.get(name);
    if (value !== null) query.set(name, value);
  }
  try {
    const upstream = await fetcher(`${base.replace(/\/$/, '')}/api/v1/${endpoint}?${query}`, {
      method: request.method, headers, body, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15_000)
    });
    const responseHeaders = new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff' });
    for (const name of ['Retry-After', 'WWW-Authenticate']) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (upstream.status >= 500) return failure(503, 'Service indisponible.');
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch { return failure(503, 'Service indisponible.'); }
}
