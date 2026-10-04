"""Focused offline checks for opt-in completed-export orchestration only."""
import contextlib
import datetime as dt
import io
import json
import os
import pathlib
import shlex
import tempfile
import unittest
from unittest import mock

import export_completed_run as exporter
import quality_handoff as quality

RUN_ID = 'SyntheticRun123'
TOKEN = 'synthetic-test-credential'


def fixture(*, age_hours=0, empty=False, failed=False):
    finish = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2, hours=age_hours)
    start = finish - dt.timedelta(minutes=1)
    run = {'id': RUN_ID, 'actId': exporter.ACTOR_ID, 'status': 'SUCCEEDED',
           'startedAt': start.isoformat(), 'finishedAt': finish.isoformat(),
           'buildNumber': 'synthetic'}
    output = {'generatedAt': finish.isoformat(), 'status': 'FAILED_QUALITY_GATE' if failed else 'SUCCEEDED',
              'qualityError': 'Synthetic gate failure' if failed else None,
              'eventsEmitted': 0 if empty else 1, 'companiesRequested': 1, 'companiesScanned': 1,
              'scans': [{'companyId': '101', 'complete': True, 'usable': True,
                         'stopReason': 'expected_count_reached'}]}
    rows = [] if empty else [{'companyId': '101', 'jobId': '1001', 'companyName': 'Synthetic company',
                             'title': 'Private synthetic role', 'eventType': 'new',
                             'detectedAt': finish.isoformat(), 'source': 'linkedin_public_jobs'}]
    return run, output, rows


def commit_raw(base, values=None):
    run, output, rows = fixture() if values is None else values
    files = dict(zip(('run.json', 'OUTPUT.json', 'rows.json'), map(exporter.encoded, (run, output, rows))))
    files['export-manifest.json'] = exporter.encoded({
        'runId': RUN_ID, 'actorId': exporter.ACTOR_ID,
        'files': {name: {'bytes': len(data), 'sha256': exporter.sha256(data)} for name, data in files.items()},
    })
    files['EXPORT_READY'] = b'Complete raw export only. Run quality_handoff.py before use.\n'
    return exporter.commit_export(base, RUN_ID, files)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve() / 'private'

    def cli(self, values=None, handoff=True, after_export=None):
        def exported(api, run_id, out, **options):
            self.assertEqual(run_id, RUN_ID)
            result = commit_raw(pathlib.Path(out), values)
            if after_export:
                after_export(result)
            return result
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ['--run-id', RUN_ID, '--out', str(self.base)] + (['--handoff'] if handoff else [])
        with mock.patch.object(exporter, 'token_from_environment', return_value=TOKEN), \
                mock.patch.object(exporter, 'ApifyGET', return_value=mock.Mock(token=TOKEN)), \
                mock.patch.object(exporter, 'export_completed_run', side_effect=exported) as export, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = exporter.main(args)
        return code, stdout.getvalue(), stderr.getvalue(), export

    def test_default_stdout_and_behavior_are_unchanged(self):
        with mock.patch.object(exporter, 'handoff_from_export') as handoff:
            code, out, err, export = self.cli(handoff=False)
        destination = self.base / RUN_ID
        command = ['python3', str(pathlib.Path(exporter.__file__).absolute().with_name('quality_handoff.py')),
                   '--run', str(destination / 'run.json'), '--output', str(destination / 'OUTPUT.json'),
                   '--rows', str(destination / 'rows.json'), '--out', str(self.base / (RUN_ID + '-handoff'))]
        self.assertEqual(out, 'Complete private export saved. No Actor was started; no rows were published.\n'
                         'Next, classify completeness and freshness:\n' +
                         ' '.join(shlex.quote(piece) for piece in command) + '\n')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(export.call_count, 1)
        handoff.assert_not_called()
        self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())

    def test_existing_raw_or_handoff_fails_before_authentication(self):
        for suffix in ('', '-handoff'):
            for dangling in (False, True):
                with self.subTest(suffix=suffix, dangling=dangling):
                    base = self.base / (suffix.replace('-', '') + str(dangling))
                    base.mkdir(parents=True)
                    target = base / (RUN_ID + suffix)
                    target.symlink_to(base / 'absent') if dangling else target.mkdir()
                    with mock.patch.object(exporter, 'token_from_environment') as token, \
                            mock.patch.object(exporter, 'ApifyGET') as api, \
                            contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(exporter.main(['--run-id', RUN_ID, '--out', str(base), '--handoff']), 1)
                    token.assert_not_called(); api.assert_not_called()
                    self.assertTrue(target.is_symlink() if dangling else target.is_dir())

    def test_healthy_current_clock_handoff_commits_private_distinct_markers(self):
        with mock.patch.object(quality, 'classify', wraps=quality.classify) as classify:
            code, out, err, export = self.cli()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(classify.call_args.kwargs, {})
        self.assertEqual(export.call_count, 1)
        raw = self.base / RUN_ID; handoff = self.base / (RUN_ID + '-handoff')
        self.assertTrue((raw / 'EXPORT_READY').is_file())
        self.assertFalse((raw / 'DONE').exists())
        self.assertTrue((handoff / 'DONE').is_file()); self.assertTrue((handoff / 'HANDOFF_READY').is_file())
        self.assertFalse((handoff / 'EXPORT_READY').exists())
        summary = json.loads((handoff / 'summary.json').read_bytes())
        self.assertEqual((summary['status'], summary['readyRows'], summary['heldRows']), ('READY_FOR_RESEARCH', 1, 0))
        self.assertEqual(summary['evaluationTimeMode'], 'CURRENT_CLOCK')
        self.assertFalse(summary['applicationRoutesVerifiedByHandoff']); self.assertFalse(summary['originAttested'])
        self.assertEqual(os.stat(raw).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(handoff).st_mode & 0o777, 0o700)
        self.assertTrue(all(os.stat(file).st_mode & 0o777 == 0o600 for file in handoff.iterdir()))
        self.assertNotIn('Private synthetic role', out); self.assertNotIn(TOKEN, out)

    def test_stale_and_failed_quality_are_nonzero_preserved_diagnostics(self):
        for values in (fixture(age_hours=25), fixture(failed=True)):
            with self.subTest(output_status=values[1]['status']):
                code, out, err, export = self.cli(values)
                self.assertEqual(code, 3); self.assertEqual(export.call_count, 1)
                handoff = self.base / (RUN_ID + '-handoff')
                self.assertTrue((self.base / RUN_ID / 'EXPORT_READY').is_file())
                self.assertTrue((handoff / 'DONE').is_file()); self.assertFalse((handoff / 'HANDOFF_READY').exists())
                self.assertIn('HELD_ONLY', out); self.assertIn('held diagnostics', err)
                self.base = self.base.parent / 'second-private'

    def test_empty_valid_is_success_and_empty_held_is_nonzero(self):
        code, out, err, _ = self.cli(fixture(empty=True))
        self.assertEqual((code, err), (0, '')); self.assertIn('EMPTY_VALID_SNAPSHOT', out)
        self.assertFalse((self.base / (RUN_ID + '-handoff') / 'HANDOFF_READY').exists())
        self.base = self.base.parent / 'empty-stale'
        code, out, err, _ = self.cli(fixture(age_hours=25, empty=True))
        self.assertEqual(code, 3); self.assertIn('EMPTY_HELD_SNAPSHOT', out)

    def test_changed_raw_hash_stops_before_classification_and_retains_raw(self):
        with mock.patch.object(quality, 'classify') as classify:
            code, out, err, _ = self.cli(after_export=lambda raw: (raw / 'rows.json').write_bytes(b'[]\n'))
        self.assertEqual(code, 2); classify.assert_not_called()
        self.assertTrue((self.base / RUN_ID / 'EXPORT_READY').is_file())
        self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())
        self.assertNotIn(TOKEN, out + err)

    def test_invalid_quality_contract_is_scrubbed_and_preserves_raw(self):
        values = fixture(); values[1]['qualityError'] = {'private': 'Unprinted synthetic source detail'}
        # Raw manifest is valid but an unexpected private value must never reach stderr.
        code, out, err, _ = self.cli(values)
        self.assertEqual(code, 2)
        self.assertTrue((self.base / RUN_ID / 'EXPORT_READY').is_file())
        self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())
        self.assertNotIn(TOKEN, out + err); self.assertNotIn('qualityError', err)
        self.assertNotIn('Unprinted synthetic source detail', out + err)

    def test_source_symlink_and_invalid_marker_stop_before_classification(self):
        for fault in ('symlink', 'marker'):
            raw = commit_raw(self.base)
            if fault == 'symlink':
                source = raw / 'rows.json'; saved = self.base / 'saved'; saved.write_bytes(source.read_bytes())
                source.unlink(); source.symlink_to(saved)
            else:
                (raw / 'EXPORT_READY').write_bytes(b'DONE\n')
            with mock.patch.object(quality, 'classify') as classify:
                with self.assertRaises(exporter.ExportError):
                    exporter.handoff_from_export(raw, TOKEN)
            classify.assert_not_called()
            self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())
            self.base = self.base.parent / 'next-private'

    def test_missing_extra_or_symlink_render_artifacts_cannot_commit(self):
        original = quality.write_handoff
        for fault in ('missing', 'extra', 'symlink'):
            raw = commit_raw(self.base)
            def faulty(result, destination):
                summary = original(result, destination)
                if fault == 'missing':
                    (destination / 'DONE').unlink()
                elif fault == 'extra':
                    (destination / 'unexpected').write_bytes(b'unknown')
                else:
                    file = destination / 'ready.json'; data = file.read_bytes(); file.unlink()
                    saved = destination.parent / 'saved'; saved.write_bytes(data); file.symlink_to(saved)
                return summary
            with mock.patch.object(quality, 'write_handoff', side_effect=faulty):
                with self.assertRaises(exporter.ExportError):
                    exporter.handoff_from_export(raw, TOKEN)
            self.assertTrue((raw / 'EXPORT_READY').exists())
            self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())
            self.assertFalse(any(path.name.startswith('.') for path in self.base.iterdir()))
            self.base = self.base.parent / ('private-' + fault)

    def test_reflected_credential_in_rendered_artifact_is_never_committed(self):
        original = quality.write_handoff
        def echo(result, destination):
            summary = original(result, destination)
            (destination / 'ready.csv').write_bytes(TOKEN.encode())
            return summary
        with mock.patch.object(quality, 'write_handoff', side_effect=echo):
            code, out, err, _ = self.cli()
        self.assertEqual(code, 2); self.assertNotIn(TOKEN, out + err)
        self.assertTrue((self.base / RUN_ID / 'EXPORT_READY').exists())
        self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())

    def test_handoff_path_cannot_contain_credential(self):
        raw = commit_raw(self.base)
        with mock.patch.object(quality, 'classify') as classify:
            with self.assertRaises(exporter.ExportError):
                exporter.handoff_from_export(raw, 'Synthetic')
        classify.assert_not_called()

    def test_renderer_and_commit_errors_are_scrubbed_without_retry(self):
        for operation in ('write_handoff', 'commit_export'):
            original_commit = exporter.commit_export
            if operation == 'write_handoff':
                patch = mock.patch.object(quality, operation, side_effect=OSError(TOKEN + ' private-source'))
            else:
                def failing_commit(base, run_id, artifacts):
                    if run_id.endswith('-handoff'):
                        raise OSError(TOKEN + ' private-source')
                    return original_commit(base, run_id, artifacts)
                patch = mock.patch.object(exporter, operation, side_effect=failing_commit)
            with patch:
                code, out, err, export = self.cli()
            self.assertEqual(code, 2); self.assertEqual(export.call_count, 1)
            self.assertNotIn(TOKEN, out + err); self.assertNotIn('private-source', out + err)
            self.assertTrue((self.base / RUN_ID / 'EXPORT_READY').exists())
            self.assertFalse((self.base / (RUN_ID + '-handoff')).exists())
            self.base = self.base.parent / 'commit-failure'

    def test_concurrent_empty_target_is_preserved_by_exclusive_commit(self):
        raw = commit_raw(self.base)
        original = exporter.rename_exclusive
        target = self.base / (RUN_ID + '-handoff')
        def raced(source, destination):
            target.mkdir()
            return original(source, destination)
        with mock.patch.object(exporter, 'rename_exclusive', side_effect=raced):
            with self.assertRaises(exporter.ExportError):
                exporter.handoff_from_export(raw, TOKEN)
        self.assertTrue(target.is_dir()); self.assertEqual(list(target.iterdir()), [])
        self.assertTrue((raw / 'EXPORT_READY').exists())
        self.assertFalse(any(path.name.startswith('.') for path in self.base.iterdir()))


if __name__ == '__main__':
    unittest.main()
