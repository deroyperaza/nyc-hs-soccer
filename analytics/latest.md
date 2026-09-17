# Traffic -- not updated

_Last tried 2026-09-17T19:10:46Z._

The numbers below this line are from the last run that worked, if
there was one. This run could not get new ones.

## Why

```
HTTP 401 from api.cloudflare.com

{"success":false,"errors":[{"code":10000,"message":"Authentication error"}],"messages":[],"result":null}


Token check:
  length 53 (a Cloudflare API token is 40)
  /tokens/verify says: HTTP 401 {"success":false,"errors":[{"code":1000,"message":"Invalid API Token"}],"messages":[],"result":null}
```

## What the job could see

| variable | state |
|---|---|
| CF_API_TOKEN | set, 53 chars |
| CF_ACCOUNT_ID | set, 32 chars |
| CF_SITE_TAG | set, 32 chars |

Values are never printed here -- only whether they arrived.

