// 3.14 návrh 117: where JARVIS's anonymous weekly statistics can go – a Cloudflare Worker with one KV namespace
// (binding STATS). It keeps only the counts, per ISO week; the sender's address is never stored.
//   POST /       one report (JSON from core/jarvis/stats.py, format 1)
//   GET  /week   the summary of this week (versions, systems, tools with calls and failures)
const MAX_BYTES = 64 * 1024;

function week(d = new Date()) {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return `${t.getUTCFullYear()}-W${String(Math.ceil(((t - y) / 86400000 + 1) / 7)).padStart(2, "0")}`;
}

function clean(r) {
  if (!r || r.format !== 1 || typeof r.id !== "string" || !/^[0-9a-f]{32}$/.test(r.id)) return null;
  const tools = {};
  for (const [k, v] of Object.entries(r.tools || {}).slice(0, 2000)) {
    if (/^[a-z0-9_]{1,60}$/.test(k) && v && Number.isFinite(v.calls)) tools[k] = { calls: Math.max(0, v.calls | 0), fails: Math.max(0, v.fails | 0) };
  }
  return { id: r.id, version: String(r.version || "").slice(0, 20), os: String(r.os || "").slice(0, 12), lang: String(r.lang || "").slice(0, 5), tools };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === "/week") {
      return new Response((await env.STATS.get(`sum:${week()}`)) || "{}", { headers: { "content-type": "application/json" } });
    }
    if (req.method !== "POST") return new Response("JARVIS stats", { status: 405 });
    const body = await req.text();
    if (body.length > MAX_BYTES) return new Response("too big", { status: 413 });
    let r;
    try { r = clean(JSON.parse(body)); } catch { r = null; }
    if (!r) return new Response("bad report", { status: 400 });
    const w = week();
    const seen = `seen:${w}:${r.id}`;
    if (await env.STATS.get(seen)) return new Response("ok (already counted)", { status: 202 });
    const sum = JSON.parse((await env.STATS.get(`sum:${w}`)) || '{"installs":0,"versions":{},"os":{},"lang":{},"tools":{}}');
    sum.installs += 1;
    for (const [k, v] of [["versions", r.version], ["os", r.os], ["lang", r.lang]]) sum[k][v] = (sum[k][v] || 0) + 1;
    for (const [k, v] of Object.entries(r.tools)) {
      const t = (sum.tools[k] ||= { calls: 0, fails: 0, installs: 0 });
      t.calls += v.calls; t.fails += v.fails; t.installs += 1;
    }
    await env.STATS.put(`sum:${w}`, JSON.stringify(sum));
    await env.STATS.put(seen, "1", { expirationTtl: 14 * 86400 });
    return new Response("ok");
  },
};
