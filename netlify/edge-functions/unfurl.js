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
  if (!p) return liveOnlyCard(origin, slug, sp);

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

/* Players who have only played this season aren't in the shards -- the app
   stitches those games from the payload it boots with, which keeps the refresh
   from rewriting every shard. The edge has no such payload, so fall back to the
   name index, which does carry them and is a couple of KB per prefix. */
async function liveOnlyCard(origin, slug, sp) {
  const first = slug.split("-")[0];
  if (first.length < 2) return null;
  const r = await fetch(origin + "/data/n/" + first.slice(0, 3) + ".json");
  if (!r.ok) return null;
  const rows = await r.json();
  const hit = rows.find(function (e) { return e[1] === slug && e[2] === sp; });
  if (!hit) return null;
  const t = await fetch(origin + "/data/titles.json");
  const codes = t.ok ? ((await t.json()).codes || {}) : {};
  const school = codes[hit[3]] || "";
  const y0 = hit[4] - 1, y1 = hit[5] - 1;
  const when = y0 === y1 ? "fall " + y0 : "fall " + y0 + "\u2013" + y1;
  const bits = [];
  if (school) bits.push(school);
  bits.push(when);
  bits.push((sp === 1 ? "girls" : "boys") + " varsity");
  return { title: titleCase(hit[0]) + " \u2014 " + SITE, desc: bits.join(" \u00b7 ") };
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

const MON = ["Jan","Feb","Mar","Apr","May","Jun",
             "Jul","Aug","Sep","Oct","Nov","Dec"];
function longDate(n) {
  n = String(n || "");
  if (n.length !== 8) return "";
  return MON[+n.slice(4, 6) - 1] + " " + (+n.slice(6)) + ", " + n.slice(0, 4);
}

/* A box score is the most shared link on the site -- it is what you send
   after a game -- and it was the one that unfurled as the bare site name. */
async function gameCard(origin, id, seasonId, sp) {
  const r = await fetch(origin + "/data/s" + seasonId + ".json");
  if (!r.ok) return null;
  const season = await r.json();
  let g = null;
  for (const row of (season.G || [])) {
    if (String(row[1]) === String(id)) { g = row; break; }
  }
  if (!g) return null;

  const short = {};
  for (const t of (season.T || [])) {
    if (t[0] === g[0]) short[t[1]] = t[4] || t[2];
  }
  const home = short[g[4]] || String(g[4]);
  const away = short[g[5]] || String(g[5]);
  const hs = g[6], as = g[7];
  const played = hs != null && as != null;
  const ff = hs === 999 || as === 999;

  const bits = [];
  const day = longDate(g[2]);
  if (day) bits.push(day);
  if (ff) bits.push("Forfeit · " + (hs === 999 ? home : away) + " win");
  else if (played) bits.push("Final · " + home + " " + hs + ", " + away + " " + as);
  else if (g[3]) bits.push(String(g[3]).replace(/^0/, ""));
  bits.push((g[0] === 1 ? "girls" : "boys") + " varsity");
  return { title: home + " vs " + away + " — " + SITE, desc: bits.join(" · ") };
}

/* The rest of the app is five tabs and three history pages. They carry no
   name of their own, so a pasted link showed the site name and nothing else
   -- true, but it tells you nothing about which page you were sent. */
const SECTIONS = {
  scores:    ["Scores", "Results and kickoff times, day by day."],
  standings: ["Standings", "Every division table, sorted by record."],
  teams:     ["Teams", "Every PSAL school fielding a soccer team."],
  playoffs:  ["Playoffs", "The bracket, round by round."],
  players:   ["Players", "Search 26 seasons of PSAL players."],
  history:   ["History", "Champions, rankings and season leaders."]
};
const HISTORY = {
  champions: ["Champions", "Every PSAL soccer title, season by season."],
  rankings:  ["Rankings", "Schools ranked by how they actually played."],
  leaders:   ["Leaders", "Goals, assists, points, shots and saves."]
};
function sectionCard(parts, sp) {
  let pair = SECTIONS[parts[0]];
  if (parts[0] === "history" && HISTORY[parts[1]]) pair = HISTORY[parts[1]];
  if (!pair) return null;
  const bits = [pair[1]];
  if (parts[0] === "scores" && /^\d{4}-\d{2}-\d{2}$/.test(parts[1] || "")) {
    bits.unshift(longDate(parts[1].replace(/-/g, "")));
  }
  bits.push((sp === 1 ? "girls" : "boys") + " varsity");
  return { title: pair[0] + " — " + SITE, desc: bits.join(" · ") };
}

/* A game link only names its season when it is an archive one, so the
   current season has to come from the page itself. */
function defaultSeason(html) {
  const m = html.match(/<script id="psal-data"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null;
  try { return JSON.parse(m[1]).meta.defaultSeason; } catch (e) { return null; }
}

export default async (request, context) => {
  const url = new URL(request.url);
  const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const res = await context.next();
  const type = res.headers.get("content-type") || "";
  if (!type.includes("text/html")) return res;
  // read once: a box score route needs the payload in the page to know which
  // season "now" is, and the body can only be consumed the one time
  const html = await res.text();
  const passthrough = () => {
    const h = new Headers(res.headers);
    h.delete("content-length");
    return new Response(html, { status: res.status, headers: h });
  };

  let card = null;
  try {
    const last = parts[parts.length - 1];
    const sp = last === "girls" ? 1 : 0;
    if (parts[0] === "player" && parts[1]) card = await playerCard(url.origin, parts[1], sp);
    else if (parts[0] === "school" && parts[1]) card = await schoolCard(url.origin, parts[1]);
    else if (parts[0] === "game" && parts[1]) {
      const sid = /^\d{4}$/.test(parts[2] || "") ? parts[2] : defaultSeason(html);
      card = sid ? await gameCard(url.origin, parts[1], sid, sp) : null;
    }
    else if (SECTIONS[parts[0]]) card = sectionCard(parts, sp);
  } catch (e) {
    card = null;                       // a preview is never worth a broken page
  }
  if (!card) return passthrough();
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
