# Operating this thing

## The refresh job

`.github/workflows/refresh.yml` runs `tools/psal_refresh.py`. One workflow, one
entry point, several modes:

- **`fetch`** — the scheduled one. Pulls scores, then this season's rosters,
  then rebuilds player pages, then tops up analytics if it is more than six
  hours stale. Each of those is independently wrapped: a failure in one must
  never take a good score refresh down with it.
- **`rosters`**, **`players`** — one-shot backfills. They checkpoint to git
  every few thousand records, so a killed run resumes rather than restarts.
- **`analytics`**, **`probe`**, **`photos`**, **`audit`** — read-only or
  write-to-`probe/` investigations.

**Everything runs in CI because PSAL is not reachable from anywhere else** —
both a laptop behind a restricted network and a sandboxed container are blocked
by egress policy.

### Scheduled runs are a lottery

GitHub's cron is best-effort and drops runs freely. Over the first two days
this workflow existed, **4 of 11 scheduled slots fired**, two of them more than
four hours late. The 4pm slot — the one that matters, when games finish —
simply never ran.

Two mitigations, both in the YAML:

1. **Ask more often.** Every 20 minutes through the evening rather than hourly,
   so a dropped run costs twenty minutes instead of the night.
2. **Stay off the hour.** `13,33,53` rather than `0`. Minute zero is when
   everyone else's cron fires and contention is worst.

If a hard guarantee is ever needed, the answer is an external pinger hitting
the `workflow_dispatch` API — more moving parts and a token stored outside the
repo, but it fires when it says it will.

### CI logs cannot be read from here

GitHub's log endpoint 302s to Azure blob storage, which both available proxies
refuse. A failed run is a red X with nothing behind it.

So **failures are made to report themselves into the repo**, where a `git pull`
or a `raw.githubusercontent.com` fetch can see them:

- `analytics/latest.md` carries the reason it could not update, plus the token's
  *shape* — length, stray characters, Cloudflare's own verdict — and never any
  part of its value.
- `probe/last_build_skip.txt` appears when the roster pull or the player-page
  rebuild is skipped, and a clean run deletes it so a stale file never reads as
  a current failure.

This pattern is worth keeping. A guard that swallows an error quietly is not a
guard, it is a gag — see below.

## Analytics

Cloudflare Web Analytics, cookieless, queried through the GraphQL API by
`tools/cf_analytics.py` and written to `analytics/latest.md` and `latest.json`.
Three repository secrets, passed through the workflow's top-level `env:` block
(a secret is invisible to a step otherwise): `CF_API_TOKEN`, `CF_ACCOUNT_ID`,
`CF_SITE_TAG`.

Two things that cost an evening:

**A Cloudflare API token is exactly 40 characters.** The first one stored was
53 — a paste that caught more than the token — and Cloudflare rejected it
outright. The report now prints the length and asks `/tokens/verify` rather
than letting anyone hunt for a permissions problem that is not there.

**`site_tag` and `site_token` are different 32-hex ids.** The one in the beacon
snippet on the page is the *token*; GraphQL filters on the *tag*. Filtering on
the wrong one is not an error — it is a valid question about a site with no
traffic, and it returns a clean report full of zeros against a dashboard
showing hundreds. `resolve_site()` now asks GraphQL to group by `siteTag` with
no filter and lets the account's sites name themselves.

Note that `analytics/latest.md` commits traffic numbers to a **public** repo. No
secrets in it, but page-level view counts are visible to anyone. Move it to a
private gist if that stops being acceptable.

For reference, September 2026: ~310 visits a day, 82% mobile, almost entirely
from two parent WhatsApp groups.

## Traps

Each of these cost real time. They are here so they cost it once.

**A guard that cannot tell "broken" from "quiet".** The roster pull refuses to
write if a pull comes back empty, on the theory that a dead session returns
nothing. The first version tested for 90% empty — and games whose coach never
files stay uncovered and get retried every run, so that pool fills up as the
season goes on and the rate crosses 90% on its own. It tripped at 62 of 68 with
the service working perfectly, took the player-page rebuild down with it, and
said so only in an unreadable log. The test is now "not one game in a
meaningful pull returned anything", which is what a dead session actually looks
like.

**Caching a miss forever.** The app writes a looked-up shirt number into the
stored follow so it need not ask again — and it wrote down the misses too. For
eleven minutes the app had shirt code deployed and an index with no numbers in
it; everyone who opened the page in that window had every follow stamped "no
number" permanently. Only hits are written now.

**`fetch(cache: "force-cache")` returns stored responses regardless of
staleness.** Fine for an archived season, wrong for anything that changes.

**Importing the module that is currently `__main__`.** `psal_rosters.py` did a
plain `import psal_refresh`, which created a *second* copy of the module with
its own `_cookies = None`. Every one of 34,000 requests went out cookie-less,
bounced to Login.aspx, and retried its way to nothing — six hours of a backfill
producing empty files that looked plausible. Check `sys.modules['__main__']`
first.

**A flex item will not shrink below its content unless told it may.** A name
inside a flex row kept its full width, the button overflowed the cell and the
cell clipped it — a hard cut with no ellipsis, which reads as a rendering fault
rather than as a name that did not fit. `flex:1 1 auto; min-width:0` fixes it,
and then instantly centres the text, because the container is a `<button>` and
buttons centre their text. That pair has appeared twice.

**Flexing a heading** turns its own text into an anonymous flex item that
shrinks and wraps. "Leaders In Our" broke across two lines the moment a chip
sat beside it.

**iOS zooms when a focused input computes under 16px** and does not zoom back.
All inputs are 16px for that reason alone.

**Netlify caching** is set in `netlify.toml`: 60s for `index.html`, 300s for
`/data/*`. Long enough to matter when checking whether a fix shipped — the page
in front of you may be a minute old.

**Stale git locks.** `.git/index.lock` and `.git/rebase-merge` get left behind
when a command is interrupted, and removing them needs delete permission on the
folder. Worth knowing before concluding the repo is broken.
