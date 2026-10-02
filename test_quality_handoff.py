import copy
import csv
import datetime
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from quality_handoff import ACTOR_ID, HandoffError, classify, csv_bytes, read_json, write_handoff

AS_OF = '2026-10-02T07:00:00Z'


def fixture():
    run = {'id': 'synthetic-quality-run', 'actId': ACTOR_ID, 'buildNumber': 'synthetic',
           'status': 'SUCCEEDED', 'startedAt': '2026-10-02T05:00:00Z',
           'finishedAt': '2026-10-02T05:01:00Z'}
    scans = [{'companyId': '101', 'complete': True, 'usable': True,
              'stopReason': 'expected_count_reached'},
             {'companyId': '202', 'complete': False, 'usable': False,
              'stopReason': 'source_pagination_limit'}]
    output = {'status': 'SUCCEEDED_WITH_WARNINGS', 'qualityError': None,
              'generatedAt': '2026-10-02T05:00:59Z', 'companiesRequested': 2,
              'companiesScanned': 2, 'completeScans': 1, 'incompleteScans': 1,
              'eventsEmitted': 4, 'scans': scans}
    rows = [{'companyId': company, 'companyName': 'Synthetic company', 'jobId': job,
             'title': '=SUM(1,2)' if event == 'new' else 'Synthetic role',
             'eventType': event, 'detectedAt': '2026-10-02T05:00:30Z',
             'source': 'linkedin_public_jobs', 'verificationStatus': 'not_requested',
             'safeToPublish': None, 'reviewRequired': None,
             'jobUrl': 'https://example.invalid/jobs/' + job}
            for company, job, event in [('101', '1001', 'new'), ('101', '1002', 'closed'),
                                         ('202', '2001', 'changed'), ('303', '3001', 'new')]]
    return run, output, rows


class HandoffTests(unittest.TestCase):
    def classify(self, values=None, **options):
        return classify(*(values or fixture()), as_of=options.pop('as_of', AS_OF), **options)

    def test_partial_and_unknown_are_held_without_new_closures(self):
        result = self.classify()
        self.assertEqual((len(result['ready']), len(result['held'])), (2, 2))
        self.assertEqual(result['summary']['readyEventCounts'], {'new': 1, 'closed': 1})
        self.assertEqual(result['summary']['heldReasonCounts']['UNKNOWN_COMPANY_SCAN'], 1)
        self.assertFalse(result['summary']['applicationRoutesVerifiedByHandoff'])

    def test_partial_closed_is_never_ready(self):
        values = fixture(); values[2][2]['eventType'] = 'closed'
        result = self.classify(values)
        self.assertFalse(any(row['companyId'] == '202' for row in result['ready']))
        self.assertEqual(sum(row['eventType'] == 'closed' for row in result['held']), 1)

    def test_complete_usable_false_is_held(self):
        values = fixture(); values[1]['scans'][0]['usable'] = False
        self.assertEqual(len(self.classify(values)['ready']), 0)

    def test_invalid_boolean_marker_does_not_coerce(self):
        values = fixture(); values[1]['scans'][0]['usable'] = 'false'
        result = self.classify(values)
        self.assertTrue(all('INVALID_SCAN_MARKERS' in row['_handoff']['reasons'] for row in result['held'] if row['companyId'] == '101'))

    def test_quality_failed_scan_is_held(self):
        values = fixture(); values[1]['scans'][0]['qualityFailed'] = True
        self.assertEqual(len(self.classify(values)['ready']), 0)

    def test_nonboolean_quality_failed_is_held(self):
        values = fixture(); values[1]['scans'][0]['qualityFailed'] = 0
        self.assertEqual(len(self.classify(values)['ready']), 0)

    def test_incomplete_stop_blocks_even_true_markers(self):
        values = fixture(); values[1]['scans'][0]['stopReason'] = 'source_pagination_limit'
        self.assertEqual(len(self.classify(values)['ready']), 0)

    def test_duplicate_company_scan_holds_affected_company(self):
        values = fixture(); values[1]['scans'].append(copy.deepcopy(values[1]['scans'][0]))
        values[1].update(companiesRequested=3, companiesScanned=3, completeScans=2)
        result = self.classify(values)
        self.assertEqual(len(result['ready']), 0)
        self.assertEqual(result['summary']['heldReasonCounts']['DUPLICATE_COMPANY_SCAN'], 2)

    def test_duplicate_job_across_conflicting_events_holds_both(self):
        values = fixture(); values[2][1]['jobId'] = values[2][0]['jobId']
        self.assertEqual(len(self.classify(values)['ready']), 0)

    def test_truncated_dataset_stops_before_artifacts(self):
        values = fixture(); values[2].pop()
        with self.assertRaisesRegex(HandoffError, 'complete rows count'):
            self.classify(values)

    def test_wrong_event_counts_stop(self):
        values = fixture(); values[1]['eventsByType'] = {'new': 3, 'closed': 1}
        with self.assertRaisesRegex(HandoffError, 'event counts'):
            self.classify(values)

    def test_boolean_count_is_rejected(self):
        values = fixture(); values[1]['eventsEmitted'] = True
        with self.assertRaises(HandoffError):
            self.classify(values)

    def test_scan_count_mismatch_stops(self):
        values = fixture(); values[1]['companiesScanned'] = 1
        with self.assertRaisesRegex(HandoffError, 'scan counts'):
            self.classify(values)

    def test_quality_gate_holds_every_row_even_complete_scans(self):
        values = fixture(); values[1]['status'] = 'FAILED_QUALITY_GATE'; values[1]['qualityError'] = 'Synthetic quality failure'
        result = self.classify(values)
        self.assertEqual(len(result['ready']), 0)
        self.assertTrue(all('RUN_QUALITY_GATE' in row['_handoff']['reasons'] for row in result['held']))

    def test_platform_failure_holds_every_row(self):
        values = fixture(); values[0]['status'] = 'FAILED'
        self.assertEqual(len(self.classify(values)['ready']), 0)

    def test_stale_snapshot_holds_every_row(self):
        result = self.classify(as_of='2026-10-04T07:00:00Z')
        self.assertEqual(len(result['ready']), 0)
        self.assertEqual(result['summary']['heldReasonCounts']['STALE_SNAPSHOT'], 4)

    def test_future_snapshot_stops(self):
        with self.assertRaisesRegex(HandoffError, 'future'):
            self.classify(as_of='2026-10-02T04:00:00Z')

    def test_output_outside_run_window_stops(self):
        values = fixture(); values[1]['generatedAt'] = '2026-10-01T05:00:00Z'
        with self.assertRaisesRegex(HandoffError, 'run window'):
            self.classify(values)

    def test_old_row_in_otherwise_matching_run_is_held(self):
        values = fixture(); values[2][0]['detectedAt'] = '2026-10-01T05:00:00Z'
        self.assertEqual(len(self.classify(values)['ready']), 1)

    def test_naive_timestamp_stops(self):
        values = fixture(); values[0]['finishedAt'] = '2026-10-02T05:01:00'
        with self.assertRaisesRegex(HandoffError, 'timezone'):
            self.classify(values)

    def test_wrong_actor_stops(self):
        values = fixture(); values[0]['actId'] = 'different-actor'
        with self.assertRaisesRegex(HandoffError, 'Hiring Signals'):
            self.classify(values)

    def test_numeric_identity_does_not_join_string_identity(self):
        values = fixture(); values[2][0]['companyId'] = 101
        self.assertEqual(len(self.classify(values)['ready']), 1)

    def test_csv_formula_and_whitespace_are_escaped(self):
        values = fixture(); values[2][1]['title'] = ' \t@danger'
        result = self.classify(values)
        records = list(csv.DictReader(io.StringIO(csv_bytes(result['ready']).decode())))
        self.assertEqual(records[0]['title'], "'=SUM(1,2)")
        self.assertEqual(records[1]['title'], "' \t@danger")

    def test_empty_valid_snapshot_has_no_ready_flag(self):
        run, output, rows = fixture(); output.update(eventsEmitted=0)
        output.update(completeScans=2, incompleteScans=0)
        for scan in output['scans']:
            scan.update(complete=True, usable=True, stopReason='expected_count_reached')
        result = self.classify((run, output, []))
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory) / 'result'; write_handoff(result, out)
            self.assertEqual(result['summary']['status'], 'EMPTY_VALID_SNAPSHOT')
            self.assertTrue((out / 'DONE').is_file())
            self.assertFalse((out / 'HANDOFF_READY').exists())

    def test_bom_prefix_formula_is_escaped(self):
        values = fixture(); values[2][0]['title'] = '\ufeff =SUM(1,2)'
        result = self.classify(values)
        records = list(csv.DictReader(io.StringIO(csv_bytes(result['ready']).decode())))
        self.assertEqual(records[0]['title'], "'\ufeff =SUM(1,2)")

    def test_c0_bom_formula_prefixes_escape_csv_without_changing_json(self):
        for prefix in [chr(number) for number in range(32)] + ['\ufeff', '\ufeff\x01\t']:
            with self.subTest(prefix=repr(prefix)):
                values = fixture(); malicious = prefix + ' =SUM(1,2)'
                values[2][0]['title'] = malicious
                result = self.classify(values)
                records = list(csv.DictReader(io.StringIO(csv_bytes(result['ready']).decode())))
                self.assertTrue(records[0]['title'].startswith("'"))
                self.assertIn('=SUM(1,2)', records[0]['title'])
                self.assertNotIn('\x00', csv_bytes(result['ready']).decode())
                self.assertEqual(result['ready'][0]['title'], malicious)

    def test_symlink_artifact_is_rejected_even_when_bytes_match(self):
        result = self.classify()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); out = root / 'batch'
            write_handoff(result, out)
            external = root / 'external.json'
            (out / 'ready.json').rename(external)
            (out / 'ready.json').symlink_to(external)
            with self.assertRaisesRegex(HandoffError, 'symlinks'):
                write_handoff(result, out)

    def test_destination_symlink_is_rejected_even_when_intact(self):
        result = self.classify()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); actual = root / 'actual'
            write_handoff(result, actual)
            linked = root / 'linked'; linked.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(HandoffError, 'symlink'):
                write_handoff(result, linked)

    def test_broken_symlink_artifact_is_rejected_before_reuse(self):
        result = self.classify()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); out = root / 'batch'
            write_handoff(result, out)
            (out / 'ready.json').unlink()
            (out / 'ready.json').symlink_to(root / 'missing.json')
            with self.assertRaisesRegex(HandoffError, 'symlinks'):
                write_handoff(result, out)

    def test_timezone_overflow_is_controlled(self):
        values = fixture(); values[0]['finishedAt'] = '9999-12-31T23:59:59-14:00'
        with self.assertRaisesRegex(HandoffError, 'ISO timestamp'):
            self.classify(values)

    def test_default_clock_cli_retry_uses_identical_fresh_decision(self):
        run, output, rows = fixture()
        now = datetime.datetime.now(datetime.timezone.utc)
        start, finish = now - datetime.timedelta(minutes=2), now - datetime.timedelta(minutes=1)
        run.update(startedAt=start.isoformat(), finishedAt=finish.isoformat())
        output['generatedAt'] = (finish - datetime.timedelta(seconds=1)).isoformat()
        for row in rows:
            row['detectedAt'] = (start + datetime.timedelta(seconds=30)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            for name, data in [('run.json', run), ('OUTPUT.json', output), ('rows.json', rows)]:
                (path / name).write_text(json.dumps(data))
            command = [sys.executable, str(pathlib.Path(__file__).with_name('quality_handoff.py')),
                       '--run', str(path / 'run.json'), '--output', str(path / 'OUTPUT.json'),
                       '--rows', str(path / 'rows.json'), '--out', str(path / 'out')]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = (path / 'out/summary.json').read_bytes()
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((path / 'out/summary.json').read_bytes(), before)

    def test_default_clock_retry_cannot_reuse_newly_stale_records(self):
        base = datetime.datetime
        class Clock(base):
            instant = base.fromisoformat('2026-10-02T07:00:00+00:00')
            @classmethod
            def now(cls, tz=None):
                return cls.instant
        with tempfile.TemporaryDirectory() as directory, mock.patch('quality_handoff.dt.datetime', Clock):
            path = pathlib.Path(directory) / 'out'
            fresh = classify(*fixture()); write_handoff(fresh, path)
            Clock.instant = base.fromisoformat('2026-10-04T07:00:00+00:00')
            stale = classify(*fixture())
            self.assertEqual(len(stale['ready']), 0)
            self.assertIn('STALE_SNAPSHOT', stale['summary']['runLevelReasons'])
            with self.assertRaisesRegex(HandoffError, 'different or incomplete'):
                write_handoff(stale, path)

    def test_failed_empty_snapshot_is_held_with_quality_error(self):
        run, output, rows = fixture(); run['status'] = 'FAILED'
        output.update(eventsEmitted=0, status='FAILED_QUALITY_GATE', qualityError='Synthetic quality failure')
        result = self.classify((run, output, []))
        self.assertEqual(result['summary']['status'], 'EMPTY_HELD_SNAPSHOT')
        self.assertEqual(result['summary']['qualityError'], 'Synthetic quality failure')
        self.assertIn('RUN_NOT_SUCCESSFUL', result['summary']['runLevelReasons'])
        self.assertIn('RUN_QUALITY_GATE', result['summary']['emptySnapshotReasons'])

    def test_stale_empty_snapshot_is_held(self):
        run, output, rows = fixture(); output.update(eventsEmitted=0)
        result = self.classify((run, output, []), as_of='2026-10-04T07:00:00Z')
        self.assertEqual(result['summary']['status'], 'EMPTY_HELD_SNAPSHOT')
        self.assertIn('STALE_SNAPSHOT', result['summary']['emptySnapshotReasons'])

    def test_empty_invalid_scan_markers_are_not_labelled_valid(self):
        run, output, rows = fixture(); output.update(eventsEmitted=0)
        output['scans'][0]['usable'] = 'true'
        result = self.classify((run, output, []))
        self.assertEqual(result['summary']['status'], 'EMPTY_HELD_SNAPSHOT')
        self.assertIn('INCOMPLETE_OR_INVALID_COMPANY_SCANS', result['summary']['emptySnapshotReasons'])

    def test_complete_artifacts_and_identical_retry(self):
        result = self.classify()
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory) / 'result'
            first = write_handoff(result, out); second = write_handoff(result, out)
            self.assertEqual(first, second)
            self.assertEqual(len(json.loads((out / 'ready.json').read_text())), 2)
            self.assertTrue((out / 'HANDOFF_READY').is_file())
            self.assertEqual(set(first['artifactHashes']), {'ready.json', 'held.json', 'ready.csv', 'held.csv'})

    def test_changed_or_incomplete_destination_not_overwritten(self):
        result = self.classify()
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory) / 'result'; write_handoff(result, out)
            (out / 'ready.json').write_text('changed')
            with self.assertRaisesRegex(HandoffError, 'different or incomplete'):
                write_handoff(result, out)
            self.assertEqual((out / 'ready.json').read_text(), 'changed')

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = pathlib.Path(directory) / 'bad.json'
            for text in ['{"complete":true,"complete":false}', '[NaN]']:
                file.write_text(text)
                with self.assertRaises(HandoffError):
                    read_json(file)

    def test_source_and_verification_fields_preserved_no_availability_guess(self):
        values = fixture(); before = copy.deepcopy(values[2])
        result = self.classify(values)
        self.assertEqual(values[2], before)
        self.assertTrue(all(row['safeToPublish'] is None and row['verificationStatus'] == 'not_requested' for row in result['ready']))


if __name__ == '__main__':
    unittest.main()
