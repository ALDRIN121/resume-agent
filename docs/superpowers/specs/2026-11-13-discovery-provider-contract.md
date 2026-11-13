# Public discovery provider contract

Verified 13 November 2026. This covers GET access to configured public boards. No application endpoint is used.

| Provider | Request and identity | Source text |
| --- | --- | --- |
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true`; posting `id` identifies the public post. | Preserve title/location and full `content`, plus the original record. `meta.total`, when present, must agree with the received list before treating it as complete. [Official contract](https://docs.greenhouse.io/job-board). |
| Lever | `GET https://api.lever.co/v0/postings/{board}?mode=json&skip={offset}&limit=100`; EU uses `api.eu.lever.co`. Posting `id` is the identity. | Preserve title/categories, combined description, additional lists/closing text and salary text. Continue until an exhausted page or the explicit 1,000-record bound. [Official README](https://github.com/lever/postings-api/blob/master/README.md), inspected revision `78323fdf7d83d6e8e065e4d7f7b852dc65561a4a`. |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{board}`. | Preserve title/location/workplace type and full plain description, with HTML fallback and original record. Honor `isListed`. [Official contract](https://developers.ashbyhq.com/docs/public-job-posting-api). |

The documented Ashby schema has `jobUrl` and no posting ID field. Implementation decision: use the exact supplied hosted-job URL as the external identity. Missing identity makes that record malformed and the scan partial. Do not invent an ID from company/title or rely on an undocumented field.

Provider/region/board/external identity remains separate across sources. Similar postings may be flagged for user review and are never silently merged. Raw records and versioned extraction metadata accompany immutable job text snapshots. Oversized descriptions are reported explicitly; they are never silently truncated to the supported 48,000-character job limit.

All providers use the design's 20-board, 1,000-record-per-board, three-request concurrency, 20-second request and 10 MiB decoded-body limits. Requests use constructed provider URLs and existing public-address validation. Redirects stay on the declared provider host. Initial plus two transient attempts are journaled before calls. Failed/partial scans retain prior data. Only a clean, exhausted scan may mark a prior posting absent; that state means “not seen in the last complete scan,” not proof that an employer has closed a role.
