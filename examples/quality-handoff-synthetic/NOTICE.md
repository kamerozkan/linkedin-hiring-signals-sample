# Offline synthetic quality handoff demo

All companies, jobs, IDs and timestamps in this folder are synthetic fixtures. example.invalid URLs are placeholders and are never fetched. The Actor ID selects the intended public contract; the synthetic run did not occur on Apify.

The four rows yield two complete-scan research records and two held diagnostics: one partial-company observation and one unknown-company record. The preserved closed fixture comes from the synthetic complete scan; the helper creates no closures. ready records do not prove application availability and are not automatically published anywhere.

Run the CLI from the repository root with --run examples/quality-handoff-synthetic/run.json --output examples/quality-handoff-synthetic/OUTPUT.json --rows examples/quality-handoff-synthetic/rows.json --out .handoffs/synthetic-demo --as-of 2026-10-02T07:00:00Z. No token, network request or charge is required. expected-summary.json is the deterministic classification summary, before local artifact hashes are added.
