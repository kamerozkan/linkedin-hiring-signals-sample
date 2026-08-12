> **Live Actor:** [Run LinkedIn Hiring Signals on Apify](https://apify.com/kamerozkan/linkedin-hiring-signals)

# LinkedIn Hiring Signals: Sample Inputs and Event Schema

[![Apify Actor](https://img.shields.io/badge/Apify-Run%20Actor-00c7b7?logo=apify)](https://apify.com/kamerozkan/linkedin-hiring-signals)
![Release](https://img.shields.io/badge/release-0.2.28-2f855a)
![Release QA](https://img.shields.io/badge/0.2.28%20exact--build%20QA-1%2F1%20succeeded-2f855a)
![Schema](https://img.shields.io/badge/schema-JSON%20Schema%202020--12-4c1)
![License](https://img.shields.io/badge/license-MIT-blue)

Monitor public LinkedIn company job pages and receive typed records for new, changed, reopened, closed, and current postings. The Actor keeps watchlist state between runs, so it can report lifecycle changes instead of treating every scan as unrelated.

This repository contains three copy-ready inputs, privacy-minimized output examples, and the dataset contract in [`dataset_record.schema.json`](dataset_record.schema.json).

## Recommended quick start

Copy [`01_github_changes_only.json`](01_github_changes_only.json) into the Actor input:

```json
{
  "companies": [
    "https://www.linkedin.com/company/github/"
  ],
  "stateNamespace": "auto",
  "closureConfirmationScans": 2,
  "emitInitialSnapshot": true,
  "emitCurrentSnapshot": false,
  "strictClosureQualityGate": false,
  "verifyApplyLinks": false
}
```

Save it as an Apify Task and schedule it daily. The first run emits the current GitHub openings as `new`. Later runs emit only changes by default.

Keep `stateNamespace` set to `auto` for saved Tasks. Each Task receives an isolated namespace. API callers should use one stable, unique namespace for each independent watchlist.

Accepted company values are:

- canonical LinkedIn company URLs
- LinkedIn company jobs or search URLs containing `f_C`
- numeric LinkedIn company IDs

Use the current canonical company URL. If an obsolete slug redirects to another company, the Actor rejects that scan instead of returning plausible data for the wrong organization.

## Use cases

### Recruiting and talent intelligence

Monitor competitors or target employers for new, changed, reopened, and confirmed closed roles. Send the change feed to an internal dashboard, Slack workflow, or recruiting system without collecting applicant or recruiter profiles.

### B2B sales and account research

Watch target accounts for company-level hiring signals such as a new function, location, or sustained expansion. Route relevant events to a CRM or alert workflow to help teams prioritize timely account research.

### Portfolio and market monitoring

Track hiring direction across a portfolio, supplier set, or market segment. Preserve a dated feed of openings and closures for trend analysis instead of repeatedly comparing full snapshots by hand.

## Three input examples

### 1. Changes-only monitoring, recommended

[`01_github_changes_only.json`](01_github_changes_only.json) emits the first snapshot and then only lifecycle changes. Optional apply-link verification is off, and safe partial results do not fail an otherwise useful run.

### 2. Full current snapshot

[`02_github_current_snapshot.json`](02_github_current_snapshot.json) sets `emitCurrentSnapshot` to `true`, so unchanged open jobs are included on every run. Use this for exports and inventory health checks. It creates more dataset rows than changes-only monitoring.

### 3. Official apply-link verification

[`03_github_verified_apply_links.json`](03_github_verified_apply_links.json) enables the separate apply-link verifier with explicit job and spend limits. Verification can add an official application URL, current status, confidence, and ghost-job risk to each submitted event.

Verification is optional, off by default, and billed separately by the verifier Actor. Keep it off until those enriched fields are needed.

## What the Actor returns

- `new`: first time a job is seen
- `changed`: title, location, company, URL, or posting date changed
- `reopened`: a previously closed job reappears
- `closed`: absent from the configured number of complete scans
- `current`: unchanged open job when full-snapshot mode is enabled

Each dataset row includes company and job identifiers, title, location, job URL, posting and detection timestamps, changed fields, event type, and optional verification fields.

The included output records have different provenance:

- [`01_live_new_official_apply.json`](01_live_new_official_apply.json) is a privacy-minimized excerpt from an earlier successful live run.
- [`02_replay_changed_location.json`](02_replay_changed_location.json) is a deterministic `changed` fixture.
- [`03_replay_closed_confirmed.json`](03_replay_closed_confirmed.json) is a deterministic `closed` fixture after two complete absence scans.

These records validate the public schema. They are not presented as customer activity or as the output of the 0.2.28 release QA run. See [`DATA_NOTICE.md`](DATA_NOTICE.md) for exact provenance and limitations.

The captured live record uses `tiny-spec-inc`, Slack's legacy LinkedIn company slug at the time of that run.

The `OUTPUT` key-value-store record provides company coverage, completeness, warnings, failures, jobs seen, events emitted, verification, webhook delivery, rolling SLOs, and billing counters.

## Safe partial results

LinkedIn public guest pages can occasionally return a rate limit, repeated page, or incomplete inventory. The Actor preserves useful results without inventing closures:

- incomplete scans never advance missing-job counters
- incomplete scans never emit `closed`
- incomplete company scans are not billed as completed company scans
- failed or unusable companies appear in the run summary
- useful results from other companies remain available with explicit warnings
- a run fails when no requested company produces usable inventory

The normal default is `strictClosureQualityGate: false`. Set it to `true` only when the entire run must fail below 95% closure-safe company coverage. A strict-gate failure preserves diagnostic dataset output but does not commit watchlist state, webhooks, or completed company-scan billing.

Two complete missing scans are required before a job closes by default. Increase `closureConfirmationScans` for more conservative closure detection.

## Release 0.2.28 evidence

The 2026-08-12 production build is `0.2.28`, build ID `xn6xxoO0lOPW2BHDS`. Both `latest` and `beta` point to this exact build. Its exact-build production smoke completed 1 of 1 run successfully:

- run `VvDekUpcdKmFFJGC6` monitored the canonical GitHub company URL
- dataset `Vm4uvM7pp5pO3SsMk` contains 82 GitHub `new` events
- 1 of 1 requested companies produced a complete scan, for 100% scan success and 100% closure-safe coverage
- the run reported zero warnings and zero failures
- recorded charge events were one company scan, 82 dataset rows, and one Actor start; because this was an owner QA run, accounted creator revenue was $0

The Store exposes three public Examples:

- [Monitor GitHub job changes](https://apify.com/kamerozkan/linkedin-hiring-signals/examples/track-verified-company-hiring-signals), task `6QgKcyXw08FiHSvlW`
- [Compare GitHub and Slack hiring](https://apify.com/kamerozkan/linkedin-hiring-signals/examples/compare-github-and-slack-hiring), task `7NsYRLjycKA3ie3AV`
- [Verify a Slack job apply link](https://apify.com/kamerozkan/linkedin-hiring-signals/examples/verify-a-slack-job-apply-link), task `UQtqO2vnNf6s2m1lB`

Their current public runs all succeeded on 0.2.27 and remain valid configuration and output demonstrations. They are not counted as 0.2.28 release evidence. The prior 0.2.27 isolated release matrix completed 8 of 8 runs successfully and remains documented in [`DATA_NOTICE.md`](DATA_NOTICE.md).

Apify's historical public 30-day success percentage includes older external runs and is not reset by a deployment, so it should not be interpreted as the 0.2.28 exact-build score.

## Pricing

The Actor uses pay-per-event pricing. Current completed company-scan prices are:

- Free: $0.005 per company scan
- Bronze: $0.0045 per company scan
- Silver: $0.004 per company scan
- Gold and above: $0.0035 per company scan
- Dataset row: $0.00001
- Actor start: $0.00005

Incomplete company scans are not charged as completed company scans. Platform usage for this Actor is included in its event pricing. Optional apply-link verification is billed separately at the price shown on the [verifier Store page](https://apify.com/kamerozkan/linkedin-job-apply-link-verifier).

Approximate monthly monitoring costs at the Free-tier company-scan price, using a 30-day month:

| Schedule | Completed company scans | Company-scan cost |
| --- | ---: | ---: |
| 10 companies once daily | 300 | about $1.50/month |
| 100 companies once daily | 3,000 | about $15/month |
| 100 companies every 6 hours | 12,000 | about $60/month |

These estimates assume complete scans, changes-only mode, and verification turned off. Actor starts and emitted dataset rows add small variable charges; optional apply-link verification is billed separately. Bronze, Silver, Gold, Platinum, and Diamond company-scan rates are lower than the Free-tier rate used above.

## Reliability boundaries

The crawler reads LinkedIn's reported inventory total as a coverage target, maintains session identity within an attempt, paginates by actual returned jobs, retries transient failures with independent sessions, and requires explicit no-results evidence before accepting an empty inventory.

The design favors delayed or missed closures over false closures. Public endpoints can still change, throttle, block, or return partial inventory. Polling cadence determines detection latency.

`closed` means a posting was absent from the configured number of complete scans. It does not prove the role was filled, cancelled, or never existed. `ghostJobRisk` is a conservative heuristic, not proof of employer intent.

## Privacy and responsible use

The output excludes recruiter names, personal profile links, emails, phone numbers, applicant identities, resumes, and raw job descriptions. It processes public company job listings and lifecycle facts.

This privacy-minimized design is not a blanket legal guarantee. Users remain responsible for applicable law, platform terms, retention rules, and downstream use. The Actor is not an official LinkedIn integration and is not endorsed by LinkedIn.

## Validate the samples

The repository check uses only Node.js built-ins:

```bash
npm test
```

It parses every JSON file, validates the three input contracts, checks output records against the public schema, verifies local Markdown links, and rejects Unicode U+2014.

## Related links

- [Run LinkedIn Hiring Signals](https://apify.com/kamerozkan/linkedin-hiring-signals)
- [Run the apply-link verifier](https://apify.com/kamerozkan/linkedin-job-apply-link-verifier)
- [Read the sample data notice](DATA_NOTICE.md)
- [Inspect the output schema](dataset_record.schema.json)
