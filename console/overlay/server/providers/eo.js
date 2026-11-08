// GroundProof provider for God's Eye View: proxies /api/eo/* to the GroundProof API.
// The service token stays server-side (GP_API_EMAIL/GP_API_PASSWORD -> JWT, never sent to the browser).
// Mirrors the provider pattern of server/providers/firePerimeters.js (Vite plugin with configureServer).
const BASE = (process.env.GP_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const ALLOWED = [
  [/^GET$/, /^\/plots\.geojson$/, '/api/eo/plots.geojson'],
  [/^GET$/, /^\/alerts$/, '/api/alerts'],
  [/^GET$/, /^\/alerts\/\d+\/preview\/(before|after)$/, null],
  [/^POST$/, /^\/quote-area$/, '/api/tasking/quote-area'],
  [/^POST$/, /^\/upload$/, '/api/plots/upload'],
];

export function eoProxy({ fetchImpl = (...a) => globalThis.fetch(...a) } = {}) {
  let token = null, tokenAt = 0;
  async function auth() {
    if (token && Date.now() - tokenAt < 3_000_000) return token;
    const r = await fetchImpl(`${BASE}/api/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: process.env.GP_API_EMAIL, password: process.env.GP_API_PASSWORD }),
    });
    if (!r.ok) throw new Error('eo_auth_failed');
    token = (await r.json()).access_token; tokenAt = Date.now();
    return token;
  }
  async function handler(req, res) {
    const path = new URL(req.url, 'http://x').pathname;
    const rule = ALLOWED.find(([m, p]) => m.test(req.method) && p.test(path));
    if (!rule) { res.statusCode = 404; return res.end('{"error":"unknown_route"}'); }
    try {
      const target = rule[2] ?? `/api${path.replace(/^\/alerts/, '/alerts')}`;
      const qs = new URL(req.url, 'http://x').search;
      const chunks = []; for await (const c of req) chunks.push(c);
      const upstream = await fetchImpl(`${BASE}${target}${qs}`, {
        method: req.method,
        headers: { Authorization: `Bearer ${await auth()}`, ...(req.headers['content-type'] ? { 'Content-Type': req.headers['content-type'] } : {}) },
        body: req.method === 'POST' ? Buffer.concat(chunks) : undefined,
        signal: AbortSignal.timeout(60_000), redirect: 'error',
      });
      res.statusCode = upstream.status;
      res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/json');
      res.end(Buffer.from(await upstream.arrayBuffer()));
    } catch { res.statusCode = 502; res.end('{"error":"eo_unavailable"}'); }
  }
  return {
    name: 'groundproof-eo',
    configureServer({ middlewares }) { middlewares.use('/api/eo', handler); },
    configurePreviewServer({ middlewares }) { middlewares.use('/api/eo', handler); },
  };
}
