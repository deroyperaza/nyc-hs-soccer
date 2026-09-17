#!/usr/bin/env python3
"""Pull traffic out of Cloudflare Web Analytics and write it into the repo.

Neither this container nor the laptop can reach api.cloudflare.com -- both sit
behind egress allowlists that don't include it -- so this runs in CI, where the
network is open, and commits what it finds. That also means the numbers are
readable without logging into a dashboard at all.

Needs three things in the environment:
  CF_API_TOKEN   a read-only token with Account Analytics: Read
  CF_ACCOUNT_ID  the account that owns the Web Analytics site
  CF_SITE_TAG    the site tag -- the same value as the beacon token in the page

Cloudflare counts a *visit* as a pageview whose referrer was a different host,
which is the number to trust here: the app rewrites its own URL as you navigate,
so its pageview count runs about double.
"""
import json, os, sys, urllib.request, urllib.error, datetime, traceback

API = "https://api.cloudflare.com/client/v4/graphql"

QUERY = """
query Traffic($account: String!, $site: String!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: {accountTag: $account}) {
      byDay: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $site, datetime_geq: $start, datetime_leq: $end}
        limit: 100
        orderBy: [date_ASC]
      ) { count sum { visits } dimensions { date } }

      topPaths: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $site, datetime_geq: $start, datetime_leq: $end}
        limit: 20
        orderBy: [count_DESC]
      ) { count sum { visits } dimensions { requestPath } }

      referrers: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $site, datetime_geq: $start, datetime_leq: $end}
        limit: 10
        orderBy: [count_DESC]
      ) { count dimensions { refererHost } }

      countries: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $site, datetime_geq: $start, datetime_leq: $end}
        limit: 10
        orderBy: [count_DESC]
      ) { count dimensions { countryName } }

      devices: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $site, datetime_geq: $start, datetime_leq: $end}
        limit: 10
        orderBy: [count_DESC]
      ) { count dimensions { deviceType } }
    }
  }
}
"""


def token_shape(token):
    """Say what is wrong with a token without ever saying what it is.

    A Cloudflare API token is 40 characters of [A-Za-z0-9_-]. Anything else is
    a paste that picked up more than the token -- which is worth knowing before
    anyone goes hunting for a permissions problem that isn't there.
    """
    lines = ["Token check:",
             "  length %d (a Cloudflare API token is 40)" % len(token)]
    stray = sorted(set(c for c in token if not (c.isalnum() or c in "_-")))
    if stray:
        lines.append("  contains characters a token never has: %s"
                     % " ".join(repr(c) for c in stray))
    try:
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=30) as r:
            v = json.load(r)
        lines.append("  /tokens/verify says: %s" % json.dumps(v.get("result"))[:200])
    except urllib.error.HTTPError as e:
        lines.append("  /tokens/verify says: HTTP %s %s"
                     % (e.code, e.read().decode("utf-8", "replace")[:200]))
    except Exception as e:
        lines.append("  /tokens/verify unreachable: %r" % (e,))
    return "\n".join(lines)


class Unavailable(Exception):
    """Cloudflare would not answer. Carries text safe to commit to a repo."""


def ask(token, variables):
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise Unavailable("HTTP %s from api.cloudflare.com\n\n%s\n\n%s"
                          % (e.code, detail, token_shape(token)))
    except Exception as e:
        raise Unavailable("could not reach api.cloudflare.com: %r" % (e,))
    if out.get("errors"):
        raise Unavailable("Cloudflare returned errors:\n\n%s"
                          % json.dumps(out["errors"], indent=1)[:1500])
    accounts = (out.get("data") or {}).get("viewer", {}).get("accounts")
    if not accounts:
        raise Unavailable("No account matched CF_ACCOUNT_ID. Check the id, and "
                          "that the token carries Account Analytics: Read on "
                          "that account.")
    return accounts[0]


def table(rows, key, label, total):
    if not rows:
        return "_none_\n"
    out = ["| %s | views | share |" % label, "|---|---:|---:|"]
    for r in rows:
        name = r["dimensions"][key] or "(direct)"
        n = r["count"]
        out.append("| %s | %d | %.0f%% |" % (name, n, 100.0 * n / total if total else 0))
    return "\n".join(out) + "\n"


def build():
    token = os.environ.get("CF_API_TOKEN", "").strip()
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    site = os.environ.get("CF_SITE_TAG", "").strip()
    missing = [n for n, v in [("CF_API_TOKEN", token), ("CF_ACCOUNT_ID", account),
                              ("CF_SITE_TAG", site)] if not v]
    if missing:
        raise Unavailable("These are not set in the job's environment: %s.\n\n"
                          "They come from repository secrets, and a secret is only\nvisible to a workflow if the YAML passes it through `env:`."
                          % ", ".join(missing))

    days = int(os.environ.get("CF_DAYS", "30"))
    end = datetime.datetime.utcnow().replace(microsecond=0)
    start = end - datetime.timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    data = ask(token, {"account": account, "site": site,
                       "start": start.strftime(fmt), "end": end.strftime(fmt)})

    by_day = data["byDay"]
    views = sum(r["count"] for r in by_day)
    visits = sum(r["sum"]["visits"] for r in by_day)
    today = end.strftime("%Y-%m-%d")
    yday = (end - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    pick = lambda d: next((r for r in by_day if r["dimensions"]["date"] == d), None)
    t, y = pick(today), pick(yday)

    md = ["# Traffic", "",
          "_%s, last %d days. Cloudflare Web Analytics, cookieless._" % (end.strftime(fmt), days), "",
          "| | visits | pageviews |", "|---|---:|---:|",
          "| today | %s | %s | " % (t["sum"]["visits"] if t else 0, t["count"] if t else 0),
          "| yesterday | %s | %s |" % (y["sum"]["visits"] if y else 0, y["count"] if y else 0),
          "| %d days | %d | %d |" % (days, visits, views), "",
          "Pageviews run roughly double: the app rewrites its own URL as you move",
          "around, and each rewrite is a beacon. Visits counts one per arrival, so",
          "that is the number that means something.", "",
          "## By day", "", "| date | visits | pageviews |", "|---|---:|---:|"]
    for r in by_day[-days:]:
        md.append("| %s | %d | %d |" % (r["dimensions"]["date"], r["sum"]["visits"], r["count"]))
    md += ["", "## Most-read pages", "", table(data["topPaths"], "requestPath", "path", views),
           "## Where people came from", "", table(data["referrers"], "refererHost", "referrer", views),
           "## Countries", "", table(data["countries"], "countryName", "country", views),
           "## Devices", "", table(data["devices"], "deviceType", "device", views)]

    repo = os.environ.get("PSAL_BASE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outdir = os.path.join(repo, "analytics")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "latest.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(outdir, "latest.json"), "w") as f:
        json.dump({"generated": end.strftime(fmt), "days": days,
                   "visits": visits, "pageviews": views,
                   "byDay": [{"date": r["dimensions"]["date"],
                              "visits": r["sum"]["visits"], "views": r["count"]}
                             for r in by_day],
                   "topPaths": [{"path": r["dimensions"]["requestPath"],
                                 "views": r["count"]} for r in data["topPaths"]]},
                  f, indent=1)
    print("wrote analytics/latest.md -- %d visits, %d pageviews over %d days"
          % (visits, views, days))


def report_failure(why):
    """Write the reason into the repo instead of dying in a log nobody reads.

    The refresh job's logs live behind a redirect that neither my laptop nor
    the container can follow, so a failure that only exists in CI output is a
    failure I cannot see. Committing it costs one line of diff and means the
    next `git pull` explains itself.
    """
    repo = os.environ.get("PSAL_BASE",
                          os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outdir = os.path.join(repo, "analytics")
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = {n: ("set, %d chars" % len(os.environ.get(n, "")))
            if os.environ.get(n) else "EMPTY"
            for n in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_SITE_TAG")}
    body = ["# Traffic -- not updated", "",
            "_Last tried %s._" % stamp, "",
            "The numbers below this line are from the last run that worked, if",
            "there was one. This run could not get new ones.", "",
            "## Why", "", "```", why.rstrip(), "```", "",
            "## What the job could see", "",
            "| variable | state |", "|---|---|"]
    body += ["| %s | %s |" % (k, v) for k, v in seen.items()]
    body += ["", "Values are never printed here -- only whether they arrived.", ""]
    with open(os.path.join(outdir, "latest.md"), "a+") as f:
        f.seek(0)
        prev = f.read()
    keep = prev.split("\n# Traffic -- not updated")[0]
    if keep.startswith("# Traffic -- not updated"):
        keep = ""
    with open(os.path.join(outdir, "latest.md"), "w") as f:
        f.write("\n".join(body) + ("\n---\n\n" + keep if keep.strip() else "\n"))
    print("analytics unavailable -- wrote the reason to analytics/latest.md")
    print(why)


def main():
    """Never raises. An analytics hiccup must not fail a scores refresh."""
    try:
        build()
    except Unavailable as e:
        report_failure(str(e))
    except Exception:
        report_failure(traceback.format_exc()[-1500:])


if __name__ == "__main__":
    main()
