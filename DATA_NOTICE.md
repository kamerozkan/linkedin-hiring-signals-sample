# Data Notice

## Purpose

This repository is a technical sample for the [LinkedIn Hiring Signals Actor](https://apify.com/kamerozkan/linkedin-hiring-signals). It demonstrates input configuration, output shape, lifecycle semantics, and conservative consumer decisions.

It is not a bulk dataset, a list of people, or a claim of comprehensive LinkedIn coverage.

## Current release audit

The following production state was verified through the Apify API and Console on 2026-08-11:

| Item | Verified value |
|---|---|
| Actor | `kamerozkan/linkedin-hiring-signals` |
| Actor ID | `ujkEG4gpQNbpYOQcc` |
| Public | `true` |
| Release | `0.2.27` |
| Build | `bEfbjGAqzUnzCbDT4`, status `SUCCEEDED` |
| Promoted tags | `latest`, `beta` |
| Isolated release QA | 7 of 7 runs `SUCCEEDED` |

The 0.2.27 release matrix covered:

1. Canonical GitHub URL: run `ZAzoHlkhm7uKqB9DH`, 85 events.
2. Numeric Slack company ID: run `q986J9PRqcGaCnGNT`, 18 events.
3. LinkedIn jobs URL containing `f_C`: run `i0kWIS0r2uXrla90q`, 18 events.
4. Repeat GitHub state: run `WlwTds4Njwy5BIutu`, zero duplicate current rows.
5. GitHub plus Slack: run `R4g9ZIgw2JRFEe9Fu`, 103 events.
6. Verification enabled: parent run `Eb8zhEkDfSwSGAfJA`, one submitted child job, one valid result, 18 parent events.
7. Safe partial result: run `eDsnNlzth14ZsZIfT`, 85 valid GitHub events retained while an obsolete Zoom slug was rejected and reported in two warnings.

All seven runs used exact build 0.2.27. This cohort validates the current release behavior. Apify's public 30-day Actor success statistic separately includes historical external runs on older builds and does not reset when a new build is deployed.

## Output sample audit

The output fixtures predate 0.2.27 and retain their original provenance. The following source run was verified on 2026-07-28:

| Item | Verified value |
|---|---|
| Source run | `WEGdccXtGUhn6W3K3` |
| Source build | `0.2.19` |
| Source dataset | `LDdvGJOkttkFGoCQi` |
| Source dataset records | 25 |

The live output excerpt is not presented as an output from 0.2.27. The release matrix above is the separate runtime evidence for the current build.

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
