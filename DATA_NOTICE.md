# Data Notice

## Purpose

This repository is a technical sample for the [LinkedIn Hiring Signals Actor](https://apify.com/kamerozkan/linkedin-hiring-signals). It demonstrates input configuration, output shape, lifecycle semantics, and conservative consumer decisions.

It is not a bulk dataset, a list of people, or a claim of comprehensive LinkedIn coverage.

## Current release audit

The following production state was verified through the Apify API on 2026-08-13:

| Item | Verified value |
|---|---|
| Actor | `kamerozkan/linkedin-hiring-signals` |
| Actor ID | `ujkEG4gpQNbpYOQcc` |
| Public | `true` |
| Release | `0.2.29` |
| Build | `a7hwqM4pB2CpzYZqK`, status `SUCCEEDED` |
| Promoted tags | `latest`, `beta` |
| Exact-build production QA | 2 of 2 runs `SUCCEEDED` |

The exact 0.2.29 production QA was:

1. Canonical GitHub baseline: run `STSy1VqhGybgn6Q36`, dataset `ZiA2FzQfqfd9WOXpW`.
2. Changes-only repeat: run `3dDAac1Qf6hvws4tZ`, dataset `o39RS4nZJyRltAqMc`.
3. The baseline found 77 jobs and emitted 77 unique, schema-valid `new` events. The repeat scanned the same 77 jobs and emitted zero duplicate events.
4. Both runs completed one of one requested company scans. `scanSuccessRate` and `closureSafeRate` were both `1`, or 100%.
5. Both runs reported zero warnings and zero failures.
6. Recorded charge events were two company scans, 77 dataset rows, and two Actor starts. Because these were owner QA runs, accounted creator revenue was $0.
7. The baseline and repeat stayed below the `$0.01` maximum charge and used approximately `$0.00094` and `$0.00046` of platform resources, respectively.

The Store currently exposes three public Examples:

| Example | Task ID | Current run release |
|---|---|---|
| Monitor GitHub job changes | `6QgKcyXw08FiHSvlW` | `0.2.27`, `SUCCEEDED` |
| Compare GitHub and Slack hiring | `7NsYRLjycKA3ie3AV` | `0.2.27`, `SUCCEEDED` |
| Verify a Slack job apply link | `UQtqO2vnNf6s2m1lB` | `0.2.27`, `SUCCEEDED` |

These public Example runs remain valid configuration and output demonstrations, but they are not presented as 0.2.29 release QA. After 2026-08-13 10:51Z, all three direct Example pages returned HTTP 200 with `index,follow` and self-canonical URLs.

## Prior 0.2.28 release audit

The 2026-08-12 production build was `0.2.28`, build ID `xn6xxoO0lOPW2BHDS`. Its exact-build production smoke, run `VvDekUpcdKmFFJGC6`, finished with `SUCCEEDED` and wrote 82 GitHub `new` events to dataset `Vm4uvM7pp5pO3SsMk`.

One of one requested companies produced a complete scan, `scanSuccessRate` and `closureSafeRate` were both 100%, and the run reported zero warnings and zero failures. Recorded charge events were one company scan, 82 dataset rows, and one Actor start. Because this was an owner QA run, accounted creator revenue was $0.

## Prior 0.2.27 release audit

The isolated 0.2.27 release matrix covered:

1. Canonical GitHub URL: run `ZAzoHlkhm7uKqB9DH`, 85 events.
2. Numeric Slack company ID: run `q986J9PRqcGaCnGNT`, 18 events.
3. LinkedIn jobs URL containing `f_C`: run `i0kWIS0r2uXrla90q`, 18 events.
4. Repeat GitHub state: run `WlwTds4Njwy5BIutu`, zero duplicate current rows.
5. GitHub plus Slack: run `R4g9ZIgw2JRFEe9Fu`, 103 events.
6. Verification enabled: parent run `Eb8zhEkDfSwSGAfJA`, one submitted child job, one valid result, 18 parent events.
7. Safe partial result: run `eDsnNlzth14ZsZIfT`, 85 valid GitHub events retained while an obsolete Zoom slug was rejected and reported in two warnings.
8. Public Store example: task `6QgKcyXw08FiHSvlW`, run `sG7bDec7xiolgvOae`, 85 GitHub events, zero warnings or failures.

All eight runs used exact build 0.2.27. This cohort remains historical evidence for that release. Apify's public 30-day Actor success statistic separately includes historical external runs across the 30-day window and does not reset when a new build is deployed.

## Output sample audit

The output fixtures predate 0.2.29 and retain their original provenance. The following source run was verified on 2026-07-28:

| Item | Verified value |
|---|---|
| Source run | `WEGdccXtGUhn6W3K3` |
| Source build | `0.2.19` |
| Source dataset | `LDdvGJOkttkFGoCQi` |
| Source dataset records | 25 |

The live output excerpt is not presented as an output from 0.2.29. The exact-build production QA above is the separate runtime evidence for the current build.

## Sample provenance

### Output 01

[`01_live_new_official_apply.json`](01_live_new_official_apply.json) is a privacy-minimized excerpt from the successful non-empty run and dataset identified above.

The source dataset contained 25 `new` events:

- 20 records had `verificationStatus = completed`.
- 5 records had `verificationStatus = skipped_limit`.
- 15 records had `safeToPublish = true`.
- 5 records had `safeToPublish = false`.
- 5 records had `safeToPublish = null`.

### Outputs 02 and 03

[`02_replay_changed_location.json`](02_replay_changed_location.json) and [`03_replay_closed_confirmed.json`](03_replay_closed_confirmed.json) are deterministic lifecycle replays using redacted fixture values.

They reflect the tested transition rules:

1. A normalized field change emits `changed` and names the field in `changedFields`.
2. An incomplete scan does not increment the absence counter.
3. With `closureConfirmationScans = 2`, two later complete scans that both omit the job emit `closed`.
4. Closed events use `verificationStatus = not_applicable`.

These replay records are schema examples. They are not represented as live Store output, customer activity, or observed employer behavior.

## Redactions

The live sample preserves non-personal company, role, location, status, confidence, and evidence fields needed to understand the contract. The following values were replaced with reserved `example.com` URLs or non-operational identifiers:

- LinkedIn job ID
- LinkedIn job URL
- Official apply URL

The replay samples use fictional company values and reserved URLs throughout.

## Privacy boundary

The Actor output contract does not include:

- recruiter names
- personal profile URLs
- email addresses
- phone numbers
- applicant identities
- resumes
- raw job descriptions

Do not enrich these samples with personal data unless you have an independent lawful basis and a documented need.

## Interpretation limits

- `closed` means a posting was absent after the configured number of complete scans. It does not prove the role was filled, cancelled, or never existed.
- `ghostJobRisk` is a conservative heuristic based on public status and evidence. It is not proof of employer intent.
- `safeToPublish = true` reflects the evidence observed at `verifiedAt`; links and statuses can later change.
- `verificationStatus = skipped_limit`, `missing_result`, `failed`, or `not_requested` must not be interpreted as active or expired.
- Public endpoints can change, throttle, block, or return partial inventories.
- Polling cadence determines detection latency.
- The Actor is not an official LinkedIn integration and is not endorsed by LinkedIn.

Users are responsible for reviewing applicable law, platform terms, retention rules, and downstream use requirements.

September 25, 2026 repair evidence uses owner-run tests of public company job pages. No customer run data is included. Partial samples are explicitly labeled and do not represent a complete company inventory or evidence that unobserved jobs are closed.

## Listing update on September 30, 2026

The Store title, description and search metadata were checked against the owned Actor and synchronized with this repository. This documentation update does not alter executable code, input or output schemas, recorded test outputs, artifact hashes, billing or runtime builds. Existing examples retain their original dates and validation limits. A public listing is not evidence of successful output, network acceptance or an achieved search ranking.

## Offline quality handoff on October 2, 2026

The new local helper filters exported research events using `OUTPUT.scans` quality and completeness. The bundled four-row fixture is entirely synthetic and never fetched. `quality-handoff-verification-2026-10-02.json` separately records aggregate counts and hashes from an existing October 2 owner run; its full watchlist, source rows, private inputs and local research queues are not published. Neither example establishes outside-customer usage or revenue. Research-ready does not mean verified current application availability. Actor runtime, schemas, pricing and cloud build are unchanged; no new cloud run or external delivery was started. Earlier public examples and verification dates are retained.

## Private completed-run exporter on October 2, 2026

`export_completed_run.py` removes the manual run/OUTPUT/dataset download step before the offline handoff. It uses authenticated GET requests at the fixed Apify API origin, rejects active or different-Actor runs, and checks a complete paginated dataset against OUTPUT and storage metadata before atomically saving an owner-only directory outside Git. The saved run metadata is whitelisted; inputs, logs, options and environment variables are excluded. Tokens are held only for Authorization and are excluded from URLs, errors and files.

`EXPORT_READY` confirms a complete raw snapshot, not a company quality decision or verified current application route. The separate handoff still filters incomplete scans and stale snapshots. File hashes do not attest arbitrary files as cloud originals. Before/after metadata, OUTPUT and page counts cannot detect every same-count concurrent dataset change. Failed retrievals receive no completed export marker; existing export directories and symlinks are rejected.

The exporter and its focused tests use Python standard libraries on supported macOS/Linux POSIX systems. Tests use invented HTTP responses and temporary private directories, not real credentials, source-page requests or cloud runs. Adding this exporter does not change the Actor runtime, schemas, pricing, build or watchlist state. API reads may consume account API/storage quota. It configures no recurring job, webhook, CRM, email or external publication. Actual completed owner-run retrieval, if separately verified, is source compatibility evidence rather than observed customer adoption, additional Actor output or revenue.

Dated live compatibility evidence is in [completed-export-verification-2026-10-02.json](completed-export-verification-2026-10-02.json): the existing owner run exported 708 rows in three bounded pages and the unchanged handoff retained 631 research records while holding 77 diagnostics. Raw source exports and research queues remain outside Git. This did not start a new Actor run or establish customer adoption.
