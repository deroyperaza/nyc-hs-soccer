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
import json, os, sys, urllib.request, datetime

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


def ask(token, variables):
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if out.get("errors"):
        raise SystemExit("Cloudflare said: %s" % json.dumps(out["errors"])[:400])
    accounts = out["data"]["viewer"]["accounts"]
    if not accounts:
        raise SystemExit("No account matched CF_ACCOUNT_ID -- check the id and "
                         "that the token has Account Analytics: Read on it.")
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


def main():
    token = os.environ.get("CF_API_TOKEN", "").strip()
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    site = os.environ.get("CF_SITE_TAG", "").strip()
    missing = [n for n, v in [("CF_API_TOKEN", token), ("CF_ACCOUNT_ID", account),
                              ("CF_SITE_TAG", site)] if not v]
    if missing:
        raise SystemExit("missing: %s" % ", ".join(missing))

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


if __name__ == "__main__":
    main()
