"""Synthetic tests only. No API, Actor, source-page or credential access."""
import contextlib
import copy
import io
import json
import os
import pathlib
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest import mock

import export_completed_run as exporter
import quality_handoff

RUN_ID = 'SyntheticRun123'
DATASET_ID = 'SyntheticDataset123'
STORE_ID = 'SyntheticStore123'
TOKEN = 'synthetic-private-credential-never-published'
FIXTURES = pathlib.Path(__file__).parent / 'examples' / 'quality-handoff-synthetic'


class Response:
    def __init__(self, url, value, headers=None):
        self.url, self.status, self.headers = url, 200, headers or {}
        self.body = io.BytesIO(exporter.encoded(value))
    def geturl(self):
        return self.url
    def read(self, count):
        return self.body.read(count)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class Source:
    def __init__(self):
        self.run = json.loads((FIXTURES / 'run.json').read_text())
        self.run.update(id=RUN_ID, defaultDatasetId=DATASET_ID,
                        defaultKeyValueStoreId=STORE_ID,
                        chargedEventCounts={'company-scan': 1},
                        accountedChargedEventCounts={'company-scan': 0},
                        envVars=[{'name': 'SECRET', 'value': TOKEN}],
                        privateInput={'token': TOKEN}, log=TOKEN)
        self.output = json.loads((FIXTURES / 'OUTPUT.json').read_text())
        self.rows = json.loads((FIXTURES / 'rows.json').read_text())
        self.dataset = {'id': DATASET_ID, 'itemCount': len(self.rows),
                        'modifiedAt': '2026-10-02T05:01:00Z'}
        self.requests = []
        self.fault = None
        self.output_reads = 0
        self.run_reads = 0
    def open(self, request, timeout):
        self.requests.append(request)
        assert request.get_method() == 'GET'
        assert request.get_header('Authorization') == 'Bearer ' + TOKEN
        assert TOKEN not in request.full_url
        parsed = urllib.parse.urlsplit(request.full_url)
        path = parsed.path
        if self.fault:
            injected = self.fault(request, self)
            if injected is not None:
                return injected
        if path == '/v2/actor-runs/' + RUN_ID:
            self.run_reads += 1
            return Response(request.full_url, {'data': copy.deepcopy(self.run)})
        if path == '/v2/key-value-stores/' + STORE_ID + '/records/OUTPUT':
            self.output_reads += 1
            return Response(request.full_url, copy.deepcopy(self.output))
        if path == '/v2/datasets/' + DATASET_ID:
            return Response(request.full_url, {'data': copy.deepcopy(self.dataset)})
        if path == '/v2/datasets/' + DATASET_ID + '/items':
            query = urllib.parse.parse_qs(parsed.query)
            offset, limit = int(query['offset'][0]), int(query['limit'][0])
            rows = copy.deepcopy(self.rows[offset:offset + limit])
            return Response(request.full_url, rows,
                            {'X-Apify-Pagination-Offset': str(offset),
                             'X-Apify-Pagination-Limit': str(limit),
                             'X-Apify-Pagination-Count': str(len(rows)),
                             'X-Apify-Pagination-Total': str(len(self.rows))})
        raise AssertionError('Unexpected endpoint')


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hiring-export-test-')
        self.addCleanup(self.temp.cleanup)
        # macOS /var is a symlink. The exporter intentionally rejects it.
        self.base = pathlib.Path(self.temp.name).resolve() / 'private'
        self.source = Source()
        self.api = exporter.ApifyGET(TOKEN, opener=self.source)
    def export(self, **kwargs):
        return exporter.export_completed_run(self.api, RUN_ID, self.base, **kwargs)
    def stopped(self, **kwargs):
        with self.assertRaises(exporter.ExportError) as raised:
            self.export(**kwargs)
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertFalse((self.base / RUN_ID / 'EXPORT_READY').exists())
        self.assertFalse((self.base / RUN_ID / 'DONE').exists())
        return str(raised.exception)
    def test_two_pages_full_raw_export_and_handoff_compatibility(self):
        destination = self.export(page_size=2)
        self.assertEqual(set(p.name for p in destination.iterdir()),
                         {'run.json', 'OUTPUT.json', 'rows.json', 'export-manifest.json', 'EXPORT_READY'})
        saved = {name: json.loads((destination / name).read_text())
                 for name in ('run.json', 'OUTPUT.json', 'rows.json', 'export-manifest.json')}
        self.assertEqual(saved['rows.json'], self.source.rows)
        self.assertNotIn('privateInput', saved['run.json'])
        self.assertNotIn('envVars', saved['run.json'])
        self.assertEqual(saved['run.json']['accountedChargedEventCounts'], {'company-scan': 0})
        self.assertFalse(saved['export-manifest.json']['originAttested'])
        self.assertEqual(saved['export-manifest.json']['datasetPages'], 2)
        self.assertEqual(saved['export-manifest.json']['rowsExported'], 4)
        result = quality_handoff.classify(saved['run.json'], saved['OUTPUT.json'], saved['rows.json'],
                                          as_of='2026-10-02T07:00:00Z')
        self.assertEqual(len(result['ready']), 2)
        self.assertEqual(len(result['held']), 2)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        for file in destination.iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(TOKEN.encode(), file.read_bytes())
        self.assertTrue(all(r.get_method() == 'GET' for r in self.source.requests))
    def test_empty_complete_dataset(self):
        self.source.rows = []
        self.source.dataset['itemCount'] = 0
        self.source.output['eventsEmitted'] = 0
        destination = self.export()
        self.assertEqual(json.loads((destination / 'rows.json').read_text()), [])
        self.assertFalse((destination / 'DONE').exists())
    def test_active_run_stops_before_dataset_read(self):
        self.source.run['status'] = 'RUNNING'
        self.stopped()
        self.assertEqual(len(self.source.requests), 1)
    def test_wrong_actor_stops(self):
        self.source.run['actId'] = 'WrongActor123'
        self.stopped()
    def test_storage_identity_mismatch_stops(self):
        self.source.dataset['id'] = 'OtherDataset123'
        self.stopped()
    def test_output_time_mismatch_stops(self):
        self.source.output['generatedAt'] = '2026-10-02T08:00:00Z'
        self.stopped()
    def test_metadata_count_mismatch_stops(self):
        self.source.dataset['itemCount'] -= 1
        self.stopped()
    def test_truncated_second_page_stops(self):
        def fault(request, source):
            if '/items?' in request.full_url and 'offset=2&' in request.full_url:
                return Response(request.full_url, [source.rows[2]],
                                {'x-apify-pagination-offset': '2', 'x-apify-pagination-limit': '2',
                                 'x-apify-pagination-count': '1', 'x-apify-pagination-total': '4'})
        self.source.fault = fault
        self.stopped(page_size=2)
    def test_wrong_page_offset_stops(self):
        def fault(request, source):
            if '/items?' in request.full_url:
                return Response(request.full_url, source.rows,
                                {'x-apify-pagination-offset': '2', 'x-apify-pagination-limit': '4',
                                 'x-apify-pagination-count': '4', 'x-apify-pagination-total': '4'})
        self.source.fault = fault
        self.stopped()
    def test_missing_pagination_headers_stop(self):
        self.source.fault = lambda request, source: Response(request.full_url, source.rows) if '/items?' in request.full_url else None
        self.stopped()
    def test_extra_tail_row_stops(self):
        def fault(request, source):
            if '/items?' in request.full_url and 'offset=4&' in request.full_url:
                return Response(request.full_url, [source.rows[0]],
                                {'x-apify-pagination-offset': '4', 'x-apify-pagination-limit': '1',
                                 'x-apify-pagination-count': '1', 'x-apify-pagination-total': '4'})
        self.source.fault = fault
        self.stopped()
    def test_output_mutation_after_pages_stops(self):
        def fault(request, source):
            if '/records/OUTPUT' in request.full_url and source.output_reads == 1:
                source.output['qualityError'] = 'changed during retrieval'
        self.source.fault = fault
        self.stopped()
    def test_run_storage_change_after_pages_stops(self):
        def fault(request, source):
            if '/actor-runs/' in request.full_url and source.run_reads == 1:
                source.run['defaultDatasetId'] = 'ChangedDataset123'
        self.source.fault = fault
        self.stopped()
    def test_http_failure_body_and_exception_do_not_leak_token(self):
        def fault(request, source):
            if '/items?' in request.full_url:
                raise urllib.error.HTTPError(request.full_url + TOKEN, 403, TOKEN, {}, io.BytesIO(TOKEN.encode()))
        self.source.fault = fault
        self.assertIn('HTTP failure (403)', self.stopped())
    def test_network_failure_details_do_not_leak_token(self):
        def fault(request, source):
            if '/items?' in request.full_url:
                raise urllib.error.URLError(TOKEN)
        self.source.fault = fault
        self.assertIn('transport failure', self.stopped())
    def test_redirect_returned_by_custom_opener_is_refused_before_body_read(self):
        response = Response('https://external.example/', {'secret': TOKEN})
        response.read = mock.Mock(side_effect=AssertionError('body must not be read'))
        self.source.fault = lambda request, source: response
        self.assertIn('redirect', self.stopped())
        response.read.assert_not_called()
    def test_redirect_handler_never_forwards_authorization(self):
        request = urllib.request.Request(exporter.ORIGIN + '/v2/actor-runs/' + RUN_ID,
                                         headers={'Authorization': 'Bearer ' + TOKEN})
        self.assertIsNone(exporter.NoRedirects().redirect_request(request, None, 302, TOKEN, {}, 'https://external.example/'))
    def test_relative_arbitrary_paths_and_token_query_refused_without_request(self):
        for path in ('https://external.example/', '/v2/actor-runs/' + RUN_ID + '?token=' + TOKEN,
                     '/v2/actor-runs/' + RUN_ID + '/runs', '/v2/actor-runs/../../other'):
            with self.assertRaises(exporter.ExportError):
                self.api.get(path)
        self.assertEqual(len(self.source.requests), 0)
    def test_configured_row_limit_and_bool_counts_refused(self):
        self.stopped(max_rows=3)
        self.source.output['eventsEmitted'] = True
        self.stopped()
    def test_symlink_parent_and_destination_refused_without_api(self):
        target = pathlib.Path(self.temp.name).resolve() / 'target'
        target.mkdir()
        self.base.symlink_to(target, target_is_directory=True)
        self.stopped()
        self.assertEqual(len(self.source.requests), 0)
        self.base.unlink()
        self.base.mkdir()
        (self.base / RUN_ID).symlink_to(target, target_is_directory=True)
        self.stopped()
        self.assertEqual(len(self.source.requests), 0)
    def test_git_tree_destination_refused_without_api(self):
        self.base.mkdir()
        (self.base / '.git').write_text('gitdir: elsewhere')
        self.stopped()
        self.assertEqual(len(self.source.requests), 0)
    def test_existing_export_is_never_overwritten(self):
        destination = self.export()
        hashes = {file.name: exporter.sha256(file.read_bytes()) for file in destination.iterdir()}
        with self.assertRaises(exporter.ExportError):
            self.export()
        self.assertEqual(hashes, {file.name: exporter.sha256(file.read_bytes()) for file in destination.iterdir()})
    def test_exclusive_atomic_commit_refuses_raced_empty_directory(self):
        root = pathlib.Path(self.temp.name).resolve()
        staging, destination = root / 'staged', root / 'existing'
        staging.mkdir()
        (staging / 'row').write_text('synthetic')
        destination.mkdir()
        with self.assertRaises(exporter.ExportError):
            exporter.rename_exclusive(staging, destination)
        self.assertTrue(staging.exists())
        self.assertEqual(list(destination.iterdir()), [])
    def test_write_failure_cleans_staging_and_leaves_no_ready_export(self):
        with mock.patch.object(exporter, 'rename_exclusive', side_effect=OSError(TOKEN)):
            self.stopped()
        self.assertEqual(list(self.base.iterdir()), [])
    def test_source_output_containing_credential_is_not_written(self):
        self.source.output['private'] = TOKEN
        self.stopped()
    def test_api_deadline_and_socket_timeout_are_safe(self):
        self.api.clock = lambda: self.api.deadline + 1
        self.assertIn('deadline', self.stopped())
        self.assertEqual(len(self.source.requests), 0)
        self.api = exporter.ApifyGET(TOKEN, opener=self.source)
        self.source.fault = lambda request, source: (_ for _ in ()).throw(TimeoutError(TOKEN))
        self.assertIn('deadline', self.stopped())
    def test_token_environment_and_local_file_do_not_use_actual_credentials(self):
        file = pathlib.Path(self.temp.name) / 'synthetic-token'
        file.write_text(TOKEN + '\n')
        self.assertEqual(exporter.token_from_environment({}, file), TOKEN)
        self.assertEqual(exporter.token_from_environment({'APIFY_TOKEN': TOKEN}, file), TOKEN)
        for token in ('', TOKEN + '\n', 'bad token'):
            with self.assertRaises(exporter.ExportError):
                exporter.token_from_environment({'APIFY_TOKEN': token}, file)
    def test_invalid_json_duplicate_keys_and_nonfinite_numbers_stop(self):
        for raw in (b'{"id":1,"id":2}', b'{"bad":NaN}', b'broken', b'\xff'):
            with self.assertRaises(exporter.ExportError):
                exporter.strict_json(raw)
    def test_cli_http_failure_prints_safe_category_only(self):
        def fault(request, source):
            raise urllib.error.HTTPError(request.full_url + TOKEN, 401, TOKEN, {}, io.BytesIO(TOKEN.encode()))
        self.source.fault = fault
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(exporter, 'token_from_environment', return_value=TOKEN), \
                mock.patch.object(exporter, 'ApifyGET', return_value=self.api), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = exporter.main(['--run-id', RUN_ID, '--out', str(self.base)])
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
        self.assertIn('HTTP failure (401)', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
