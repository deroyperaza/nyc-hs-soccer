/* Link previews.
 *
 * The site is one static index.html served for every route, so anything that
 * unfurls a link -- Slack, iMessage, WhatsApp, Discord -- fetches that file,
 * reads its <title>, never runs JavaScript, and shows "NYC High School Soccer"
 * whatever you linked to. The browser tab title is right because JS sets it;
 * the shared link is not, because nobody runs the JS.
 *
 * This rewrites the title and adds Open Graph tags for the routes that name
 * something specific. It runs for everyone rather than sniffing for bots:
 * Apple's preview fetcher is indistinguishable from Safari, so user-agent
 * detection would quietly fail on exactly the case that prompted this.
 */
const SITE = "NYC High School Soccer";

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}

function titleCase(s) {
  s = String(s || "");
  if (s !== s.toUpperCase()) return s;
  return s.toLowerCase().replace(/(^|[\s\-'])([a-z])/g, function (m, a, b) {
    return a + b.toUpperCase();
  });
}

/* same FNV-1a the app uses to find a player's shard */
function shardOf(key, shards) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h % (shards || 1024);
}

async function playerCard(origin, slug, sp) {
  const fetchKey = async (key) => {
    const hex = ("00" + shardOf(key, 1024).toString(16)).slice(-3);
    const r = await fetch(origin + "/data/p/" + hex + ".json");
    if (!r.ok) return null;
    const bundle = await r.json();
    return bundle[key] || null;
  };
  let key = sp + "/" + slug;
  let p = await fetchKey(key);
  if (p && p.ref) { key = p.ref; p = await fetchKey(key); }   // merged spelling
  if (!p) return null;

  let apps = 0, goals = 0, assists = 0;
  const years = [];
  (p.s || []).forEach(function (blk) {
    years.push(blk[0]);
    blk[1].forEach(function (r) { apps++; goals += r[7]; assists += r[8]; });
  });
  const name = titleCase(p.n || "");
  const bits = [];
  if (p.fn) bits.push(p.fn);
  if (years.length) {
    const y0 = Math.min.apply(null, years) - 1, y1 = Math.max.apply(null, years) - 1;
    bits.push(y0 === y1 ? "fall " + y0 : "fall " + y0 + "–" + y1);
  }
  if (apps) {
    bits.push(apps + " appearance" + (apps === 1 ? "" : "s") +
      (goals ? ", " + goals + " goal" + (goals === 1 ? "" : "s") : "") +
      (assists ? ", " + assists + " assist" + (assists === 1 ? "" : "s") : ""));
  }
  return { title: name + " — " + SITE, desc: bits.join(" · ") };
}

async function schoolCard(origin, slug) {
  const r = await fetch(origin + "/data/titles.json");
  if (!r.ok) return null;
  const t = await r.json();
  const name = t.schools && t.schools[slug];
  if (!name) return null;
  return { title: name + " — " + SITE,
           desc: "Schedule, results and rosters from the PSAL league feed." };
}

export default async (request, context) => {
  const url = new URL(request.url);
  const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const res = await context.next();
  const type = res.headers.get("content-type") || "";
  if (!type.includes("text/html")) return res;

  let card = null;
  try {
    const last = parts[parts.length - 1];
    const sp = last === "girls" ? 1 : 0;
    if (parts[0] === "player" && parts[1]) card = await playerCard(url.origin, parts[1], sp);
    else if (parts[0] === "school" && parts[1]) card = await schoolCard(url.origin, parts[1]);
  } catch (e) {
    card = null;                       // a preview is never worth a broken page
  }
  if (!card) return res;

  const html = await res.text();
  const head =
    "<title>" + esc(card.title) + "</title>" +
    '<meta property="og:title" content="' + esc(card.title) + '">' +
    '<meta property="og:description" content="' + esc(card.desc) + '">' +
    '<meta property="og:url" content="' + esc(url.href) + '">' +
    '<meta property="og:site_name" content="' + esc(SITE) + '">' +
    '<meta property="og:type" content="website">' +
    '<meta name="twitter:card" content="summary">' +
    '<meta name="twitter:title" content="' + esc(card.title) + '">' +
    '<meta name="twitter:description" content="' + esc(card.desc) + '">';

  const out = html.replace(/<title>[\s\S]*?<\/title>/, head);
  const headers = new Headers(res.headers);
  headers.delete("content-length");
  return new Response(out, { status: res.status, headers: headers });
};
