> **Live Actor:** [Run LinkedIn Company Jobs Monitor & Change Feed on Apify](https://apify.com/kamerozkan/linkedin-hiring-signals)

# LinkedIn Company Jobs Monitor & Change Feed: Samples

[![Apify Actor](https://img.shields.io/badge/Apify-Run%20Actor-00c7b7?logo=apify)](https://apify.com/kamerozkan/linkedin-hiring-signals)
![Release](https://img.shields.io/badge/release-0.2.29-2f855a)
![Release QA](https://img.shields.io/badge/0.2.29%20exact--build%20QA-2%2F2%20succeeded-2f855a)
![Schema](https://img.shields.io/badge/schema-JSON%20Schema%202020--12-4c1)
![License](https://img.shields.io/badge/license-MIT-blue)

Monitor public LinkedIn company job pages and receive typed change-feed records for new, changed, reopened, closed, and current postings. The Actor keeps watchlist state between runs, so it can report lifecycle changes instead of treating every scan as unrelated.

This repository contains three copy-ready inputs, privacy-minimized output examples, and the dataset contract in [`dataset_record.schema.json`](dataset_record.schema.json).

The product is a company and job-posting monitor, not a people-search or candidate-sourcing tool. It is designed for repeat employer watchlists where a dated change feed is more useful than repeatedly checking the same public job pages by hand.

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

## Buyer workflows

### LinkedIn job posting monitor for ATS and recruiting operations

Monitor target employers for new, changed, reopened, and confirmed closed roles. Send the dataset or webhook events to an ATS-side analytics layer, recruiting-operations dashboard, or internal alert workflow without collecting applicant or recruiter profiles.

The Actor provides a dataset, API output, and optional webhook delivery. It does not write into an ATS by itself; that final mapping remains part of the buyer's downstream automation.

### RPO and staffing-company market mapping

Create one saved Task per client, desk, geography, or employer segment and keep `stateNamespace` set to `auto`. Each Task then maintains an isolated watchlist history that can support RPO market mapping or staffing business-development research without mixing client state.

### Recruitment market intelligence API and dataset

Use changes-only mode for a dated hiring-movement feed. Use full-snapshot mode when the buyer needs the current open-job inventory on every run. The records can support employer, location, and role-family analysis, but polling cadence and public-page availability still determine what can be observed.

### Company hiring signals for B2B account research

Watch target accounts for company-level signals such as a new function, location, or sustained expansion. Route relevant events to a CRM or research queue as a reason to investigate. A hiring event is not proof of budget, purchase intent, or an open sales opportunity.

### Choose the right sample

| Buyer job | Start with | Important boundary |
| --- | --- | --- |
| ATS or recruiting-operations change feed | [`01_github_changes_only.json`](01_github_changes_only.json) | Destination-field mapping is still required |
| RPO client or market watchlist | [`01_github_changes_only.json`](01_github_changes_only.json), saved as one Task per watchlist | Keep watchlist state isolated |
| Recruitment market intelligence snapshot | [`02_github_current_snapshot.json`](02_github_current_snapshot.json) | Full snapshots create more dataset-row events |
| Official apply-route review | [`03_github_verified_apply_links.json`](03_github_verified_apply_links.json) | Verification is optional and billed separately |

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

These records validate the public schema. They are not presented as customer activity or as the output of the 0.2.29 release QA runs. See [`DATA_NOTICE.md`](DATA_NOTICE.md) for exact provenance and limitations.

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

## Release 0.2.29 evidence

The 2026-08-13 production build is `0.2.29`, build ID `a7hwqM4pB2CpzYZqK`. Both `latest` and `beta` point to this exact build. Its baseline and changes-only repeat completed 2 of 2 runs successfully:

- baseline run `STSy1VqhGybgn6Q36` monitored the canonical GitHub company URL and wrote 77 unique, schema-valid `new` rows to dataset `ZiA2FzQfqfd9WOXpW`
- changes-only repeat `3dDAac1Qf6hvws4tZ` scanned the same 77 jobs and emitted zero duplicate rows to dataset `o39RS4nZJyRltAqMc`
- both runs completed 1 of 1 requested company scans, with 100% scan success and 100% closure-safe coverage
- both runs reported zero warnings and zero failures
- recorded charge events were two company scans, 77 dataset rows, and two Actor starts; because these were owner QA runs, accounted creator revenue was $0
- the baseline and repeat stayed below the `$0.01` maximum charge and used approximately `$0.00094` and `$0.00046` of platform resources, respectively

The Store exposes three public Examples:

- [Create a GitHub job-change monitor](https://console.apify.com/create-task-from-example/6QgKcyXw08FiHSvlW), task `6QgKcyXw08FiHSvlW`
- [Create a GitHub and Slack hiring comparison](https://console.apify.com/create-task-from-example/7NsYRLjycKA3ie3AV), task `7NsYRLjycKA3ie3AV`
- [Create a Slack apply-link verification Task](https://console.apify.com/create-task-from-example/UQtqO2vnNf6s2m1lB), task `UQtqO2vnNf6s2m1lB`

Their current public runs all succeeded on 0.2.27 and remain valid configuration and output demonstrations. They are not counted as 0.2.29 release evidence. The prior 0.2.27 isolated release matrix completed 8 of 8 runs successfully and remains documented in [`DATA_NOTICE.md`](DATA_NOTICE.md).

After 2026-08-13 10:51Z, the Store and all three direct Example pages returned HTTP 200 with `index,follow` and self-canonical URLs. The Actor title, SEO description, and the corrected Compare and Verify Example descriptions matched their saved values.

Apify's historical public 30-day success percentage includes older external runs and is not reset by a deployment, so it should not be interpreted as the 0.2.29 exact-build score.

## Pricing and buyer cost model

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

### Seven-day buyer pilot

Use [`01_github_changes_only.json`](01_github_changes_only.json) as the base, expand `companies` to 25 agreed canonical company URLs, and set `strictClosureQualityGate` to `true` when the workflow must reject coverage below 95%. Save the input as one Task and run that same Task once daily for seven days so state remains comparable.

If all 25 company scans complete each day, the company-scan component is 175 scans, or `$0.875` at the Free-tier rate. Actor starts and emitted dataset rows add small variable charges.

Judge the pilot on observed evidence:

- `scanSuccessRate`, `closureSafeRate`, warnings, and failures in each `OUTPUT` record
- whether a manual sample review finds the emitted changes useful and correctly classified
- whether the dataset, API, or webhook fits the intended ATS, RPO, CRM, or analytics workflow
- measured operator time before and during the pilot
- total run charges, including any optional verification

Scale only when the measured workflow value is greater than the measured cost. The Actor does not promise time savings, placements, sales opportunities, or a particular return on investment.

To control cost, keep changes-only mode on, choose the lowest useful schedule frequency, leave verification off until its fields are needed, and use the verification job and charge limits when enabling it. The Store pricing shown at run time is authoritative.

## Reliability boundaries

The crawler reads LinkedIn's reported inventory total as a coverage target, maintains session identity within an attempt, paginates by actual returned jobs, retries transient failures with independent sessions, and requires explicit no-results evidence before accepting an empty inventory.

The design favors delayed or missed closures over false closures. Public endpoints can still change, throttle, block, or return partial inventory. Polling cadence determines detection latency.

`closed` means a posting was absent from the configured number of complete scans. It does not prove the role was filled, cancelled, or never existed. `ghostJobRisk` is a conservative heuristic, not proof of employer intent.

## FAQ for ATS, RPO, and recruitment intelligence buyers

### Is this a LinkedIn jobs scraper or a job-change monitor?

It supports both workflows. The first scheduled run can emit the current openings. Later runs return only changes by default. Set `emitCurrentSnapshot: true` when a complete current snapshot is required on every run.

### Does it integrate directly with an ATS, CRM, or BI tool?

The Actor exposes its records through the Apify dataset and API and can send non-empty event batches to an HTTPS webhook. A buyer still needs to map those fields into the destination system. No native ATS or CRM write is claimed.

### Can an RPO keep client watchlists separate?

Yes. Use one saved Task per client or market and leave `stateNamespace` as `auto`. API callers should assign one stable, unique namespace to each independent watchlist.

### Does `closed` mean that a role was filled?

No. It means the posting was absent from the configured number of complete scans. It does not prove whether the employer filled, cancelled, paused, or replaced the role.

### Why can a run succeed with warnings?

A partial run may still contain safe additions or changes for usable companies. Incomplete scans do not advance closure state and are not charged as completed company scans. Enable the strict closure-quality gate when the downstream workflow must reject coverage below 95%.

### Is complete LinkedIn coverage guaranteed?

No. Public pages can change, throttle, block, or return partial inventory. The Actor reports coverage and applies conservative closure rules so the buyer can make a workflow decision from explicit run evidence.

### Does it need a LinkedIn account or collect candidate profiles?

No LinkedIn login or user cookies are required. The output contract excludes applicant and recruiter profiles, emails, phone numbers, resumes, and raw job descriptions.

### What is charged when a scan is incomplete?

An incomplete company scan is not charged as a completed company scan. Actor-start and emitted dataset-row events, if any, remain separate. Optional official apply-link verification is billed by the verifier Actor.

## Support: share a failed run with enough evidence

For a failed, incomplete, or unexpected run:

1. Open the run in Apify Console and inspect its log and `OUTPUT` record.
2. Review the input, log, and output for client-sensitive values before sharing anything.
3. Open the Actor's [Issues page](https://apify.com/kamerozkan/linkedin-hiring-signals/issues) and include the full Console run URL, the expected result, and the observed result.
4. State whether a retry succeeded and which company input was affected. Never paste an Apify token or webhook secret into the issue text.

Apify documents that including a run URL in an Actor issue automatically grants the Actor developer access to that run and its default storages, even when general resource access is restricted. The permission is limited to the reported run and related storages. See [Apify's run-sharing documentation](https://docs.apify.com/account/collaboration/general-resource-access#automatically-sharing-runs-via-actor-issues).

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
