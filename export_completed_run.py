#!/usr/bin/env python3
"""Privately export one completed Hiring run using bounded, authenticated GETs."""
import argparse
import contextlib
import ctypes
import datetime as dt
import errno
import hashlib
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ACTOR_ID = 'ujkEG4gpQNbpYOQcc'
ORIGIN = 'https://api.apify.com'
MAX_BYTES = 50 * 1024 * 1024
TERMINAL = {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}
ID_RE = re.compile(r'[A-Za-z0-9]{4,64}')
PATH_RE = re.compile(r'/v2/(?:actor-runs/[A-Za-z0-9]{4,64}|datasets/[A-Za-z0-9]{4,64}(?:/items)?|key-value-stores/[A-Za-z0-9]{4,64}/records/OUTPUT)')


class ExportError(ValueError):
    """An error category safe to print without upstream content or credentials."""


class RequestDeadline(Exception):
    pass


def encoded(value):
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           indent=2, allow_nan=False) + '\n').encode('utf-8')
    except (TypeError, ValueError, UnicodeError):
        raise ExportError('Invalid JSON data') from None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def count(value, name, maximum=None):
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise ExportError(name + ' is invalid or exceeds the configured limit')
    return value


def identifier(value, name):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ExportError(name + ' is invalid')
    return value


def timestamp(value, name):
    if not isinstance(value, str):
        raise ExportError(name + ' is invalid')
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError):
        raise ExportError(name + ' is invalid') from None


def token_from_environment(environ=None, token_file=None):
    env = os.environ if environ is None else environ
    token = env.get('APIFY_TOKEN')
    if token is None:
        path = pathlib.Path.home() / '.apify' / 'token' if token_file is None else pathlib.Path(token_file)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
                raise ExportError('No usable APIFY_TOKEN or local Apify token file')
            token = path.read_text(encoding='utf-8').strip()
        except (OSError, UnicodeError):
            raise ExportError('No usable APIFY_TOKEN or local Apify token file') from None
    if not isinstance(token, str) or not token or len(token) > 4096 or any(ord(c) < 33 or ord(c) == 127 for c in token):
        raise ExportError('APIFY_TOKEN is invalid')
    return token


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


@contextlib.contextmanager
def request_deadline(seconds):
    # A socket inactivity timeout alone does not bound a slowly streamed body.
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, 'setitimer'):
        raise ExportError('GET client requires a POSIX main-thread deadline')
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer != (0.0, 0.0):
        raise ExportError('An existing process deadline prevents this export')
    previous_handler = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise RequestDeadline()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError()
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ExportError('API response is not strict JSON') from None


class ApifyGET:
    """Fixed-origin client. It exposes no start, POST or arbitrary-URL method."""
    def __init__(self, token, *, opener=None, timeout=20, max_seconds=120, clock=None):
        self.token = token_from_environment({'APIFY_TOKEN': token})
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ExportError('Request timeout must be greater than zero and at most 120 seconds')
        if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 3600:
            raise ExportError('Export deadline must be greater than zero and at most 3600 seconds')
        self.opener = opener or urllib.request.build_opener(NoRedirects())
        self.timeout = timeout
        self.clock = clock or time.monotonic
        self.deadline = self.clock() + max_seconds
        self.requests = 0

    def get(self, path, params=None):
        if not isinstance(path, str) or not PATH_RE.fullmatch(path):
            raise ExportError('Only supported fixed Apify GET endpoints are allowed')
        params = {} if params is None else params
        if path.endswith('/items'):
            if not isinstance(params, dict) or set(params) != {'format', 'clean', 'offset', 'limit'} or params['format'] != 'json' or params['clean'] != 'false':
                raise ExportError('Dataset GET parameters are invalid')
            count(params['offset'], 'Dataset offset', 100000)
            if count(params['limit'], 'Dataset limit', 1000) < 1:
                raise ExportError('Dataset limit is invalid')
        elif params:
            raise ExportError('This GET endpoint takes no query parameters')
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise ExportError('Export deadline exceeded')
        url = ORIGIN + path + ('?' + urllib.parse.urlencode(params) if params else '')
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token,
                                                      'Accept': 'application/json'}, method='GET')
        self.requests += 1
        try:
            with request_deadline(min(self.timeout, remaining)):
                with self.opener.open(request, timeout=min(self.timeout, remaining)) as response:
                    if response.geturl() != url:
                        raise ExportError('API redirects are refused')
                    if response.status != 200:
                        raise ExportError('API returned a non-success response')
                    raw = bytearray()
                    while True:
                        piece = response.read(min(65536, MAX_BYTES + 1 - len(raw)))
                        if not piece:
                            break
                        raw.extend(piece)
                        if len(raw) > MAX_BYTES:
                            raise ExportError('API response exceeds the private export size limit')
                        if self.clock() >= self.deadline:
                            raise ExportError('Export deadline exceeded')
                    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        except urllib.error.HTTPError as error:
            code = error.code if type(error.code) is int else 0
            raise ExportError('API HTTP failure (' + str(code) + '); response content withheld') from None
        except (RequestDeadline, TimeoutError, socket.timeout):
            raise ExportError('API GET deadline exceeded; no export committed') from None
        except (urllib.error.URLError, OSError):
            raise ExportError('API GET transport failure; details withheld') from None
        if self.clock() >= self.deadline:
            raise ExportError('Export deadline exceeded')
        return strict_json(bytes(raw)), headers


def unwrap(payload, name):
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
        raise ExportError(name + ' metadata envelope is invalid')
    return payload['data']


def sanitized_run(payload, run_id):
    source = unwrap(payload, 'Run')
    if source.get('id') != run_id or source.get('actId') != ACTOR_ID:
        raise ExportError('Run identity does not match this Hiring Actor')
    if source.get('status') not in TERMINAL:
        raise ExportError('Run is not completed; no export committed')
    start = timestamp(source.get('startedAt'), 'Run start time')
    finish = timestamp(source.get('finishedAt'), 'Run finish time')
    if finish < start:
        raise ExportError('Run time window is invalid')
    result = {key: source[key] for key in ('id', 'actId', 'status', 'startedAt', 'finishedAt')}
    for key in ('defaultDatasetId', 'defaultKeyValueStoreId'):
        result[key] = identifier(source.get(key), 'Run storage identity')
    if 'buildNumber' in source:
        value = source['buildNumber']
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value):
            raise ExportError('Run build number is invalid')
        result['buildNumber'] = value
    if source.get('buildId') is not None:
        result['buildId'] = identifier(source['buildId'], 'Run build identity')
    for key in ('chargedEventCounts', 'accountedChargedEventCounts'):
        if key in source:
            values = source[key]
            if not isinstance(values, dict) or any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', k) for k in values):
                raise ExportError('Run event counts are invalid')
            result[key] = {k: count(v, 'Run event count') for k, v in values.items()}
    return result


def dataset_snapshot(payload, dataset_id):
    source = unwrap(payload, 'Dataset')
    if source.get('id') != dataset_id:
        raise ExportError('Dataset identity does not match this run')
    result = {'id': dataset_id, 'itemCount': count(source.get('itemCount'), 'Dataset itemCount', 100000)}
    if source.get('modifiedAt') is not None:
        timestamp(source['modifiedAt'], 'Dataset modification time')
        result['modifiedAt'] = source['modifiedAt']
    return result


def checked_output(payload, run, max_rows):
    if not isinstance(payload, dict):
        raise ExportError('Run OUTPUT is not an object')
    emitted = count(payload.get('eventsEmitted'), 'OUTPUT.eventsEmitted', max_rows)
    generated = timestamp(payload.get('generatedAt'), 'OUTPUT generation time')
    slack = dt.timedelta(seconds=60)
    start = timestamp(run['startedAt'], 'Run start time')
    finish = timestamp(run['finishedAt'], 'Run finish time')
    if not start - slack <= generated <= finish + slack:
        raise ExportError('OUTPUT generation time does not belong to this run')
    for key, actual in (('runId', run['id']), ('actorId', ACTOR_ID),
                        ('datasetId', run['defaultDatasetId'])):
        if key in payload and payload[key] != actual:
            raise ExportError('OUTPUT identity does not match this run')
    if len(encoded(payload)) > MAX_BYTES:
        raise ExportError('OUTPUT exceeds the private export size limit')
    return emitted


def checked_page(payload, headers, *, offset, limit, expected):
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ExportError('Dataset page is not a JSON array of objects')
    observed = {}
    for key in ('offset', 'limit', 'count', 'total'):
        value = headers.get('x-apify-pagination-' + key)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
            raise ExportError('Dataset pagination headers are missing or invalid')
        observed[key] = int(value)
    if observed != {'offset': offset, 'limit': limit, 'count': len(payload), 'total': expected}:
        raise ExportError('Dataset pagination does not match the requested snapshot')
    if len(payload) != min(limit, max(expected - offset, 0)):
        raise ExportError('Dataset page is truncated or contains unexpected rows')
    return payload


def checked_base(base):
    path = pathlib.Path(os.path.abspath(os.path.expanduser(str(base))))
    for current in (path,) + tuple(path.parents):
        if current.is_symlink():
            raise ExportError('Export paths must not contain symlinks')
        if (current / '.git').exists() or (current / '.git').is_symlink():
            raise ExportError('Choose a private export location outside any Git working tree')
        if current.exists() and not current.is_dir():
            raise ExportError('Export parent is not a directory')
    return path


def rename_exclusive(source, destination):
    # Neither os.rename nor os.replace refuses an existing empty directory on POSIX.
    # The OS primitive commits the entire directory without replacing any destination.
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin' and hasattr(library, 'renamex_np'):
        operation = library.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = operation(os.fsencode(source), os.fsencode(destination), 0x00000004)
    elif sys.platform.startswith('linux') and hasattr(library, 'renameat2'):
        operation = library.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = operation(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise ExportError('Atomic no-overwrite export requires supported macOS or Linux')
    operation.restype = ctypes.c_int
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise ExportError('Export destination already exists; choose a new private base')
        raise ExportError('Atomic export commit failed; no destination replaced')


def commit_export(base, run_id, artifacts):
    base = checked_base(base)
    destination = base / run_id
    if destination.exists() or destination.is_symlink():
        raise ExportError('Export destination already exists; choose a new private base')
    # Every newly created ancestor is owner-only. Existing parent permissions are untouched.
    for parent in reversed((base,) + tuple(base.parents)):
        if not parent.exists():
            try:
                parent.mkdir(mode=0o700)
            except OSError:
                raise ExportError('Could not create a private export parent') from None
    checked_base(base)
    staging = pathlib.Path(tempfile.mkdtemp(prefix='.' + run_id + '-staging-', dir=str(base)))
    try:
        for name, data in artifacts.items():
            file = staging / name
            with file.open('xb') as handle:
                os.chmod(str(file), 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        checked_base(base)
        rename_exclusive(staging, destination)
        return destination
    except ExportError:
        raise
    except OSError:
        raise ExportError('Private export write failed; no export committed') from None
    finally:
        if staging.exists():
            shutil.rmtree(str(staging))


def export_completed_run(api, run_id, out, *, max_rows=100000, page_size=1000):
    identifier(run_id, 'Run ID')
    count(max_rows, 'Maximum rows', 100000)
    if count(page_size, 'Page size', 1000) < 1:
        raise ExportError('Page size must be at least one')
    base = checked_base(out)
    if api.token in str(base):
        raise ExportError('Export path contains credential data')
    destination = base / run_id
    if destination.exists() or destination.is_symlink():
        raise ExportError('Export destination already exists; choose a new private base')
    run = sanitized_run(api.get('/v2/actor-runs/' + run_id)[0], run_id)
    dataset_id, store_id = run['defaultDatasetId'], run['defaultKeyValueStoreId']
    output_path = '/v2/key-value-stores/' + store_id + '/records/OUTPUT'
    output = api.get(output_path)[0]
    expected = checked_output(output, run, max_rows)
    dataset = dataset_snapshot(api.get('/v2/datasets/' + dataset_id)[0], dataset_id)
    if dataset['itemCount'] != expected:
        raise ExportError('Dataset itemCount does not match OUTPUT; retry this completed run later')
    rows, pages, bytes_used = [], 0, 3
    while len(rows) < expected:
        offset, limit = len(rows), min(page_size, expected - len(rows))
        payload, headers = api.get('/v2/datasets/' + dataset_id + '/items',
                                   {'format': 'json', 'clean': 'false', 'offset': offset, 'limit': limit})
        page = checked_page(payload, headers, offset=offset, limit=limit, expected=expected)
        bytes_used += sum(len(encoded(row)) + 2 for row in page)
        if bytes_used > MAX_BYTES:
            raise ExportError('Complete rows exceed the private export size limit')
        rows.extend(page)
        pages += 1
    payload, headers = api.get('/v2/datasets/' + dataset_id + '/items',
                               {'format': 'json', 'clean': 'false', 'offset': expected, 'limit': 1})
    checked_page(payload, headers, offset=expected, limit=1, expected=expected)
    final_dataset = dataset_snapshot(api.get('/v2/datasets/' + dataset_id)[0], dataset_id)
    final_output = api.get(output_path)[0]
    final_run = sanitized_run(api.get('/v2/actor-runs/' + run_id)[0], run_id)
    if dataset != final_dataset or encoded(output) != encoded(final_output) or run != final_run:
        raise ExportError('Run snapshot changed during retrieval; no export committed')
    if len(rows) != expected:
        raise ExportError('Complete dataset row count does not match OUTPUT')
    artifacts = {'run.json': encoded(run), 'OUTPUT.json': encoded(output), 'rows.json': encoded(rows)}
    if any(len(data) > MAX_BYTES for data in artifacts.values()):
        raise ExportError('Export artifact exceeds the private export size limit')
    if any(api.token.encode('utf-8') in data for data in artifacts.values()):
        raise ExportError('API source contains credential data; no export committed')
    manifest = {
        'schemaVersion': 1, 'runId': run_id, 'actorId': ACTOR_ID,
        'datasetId': dataset_id, 'keyValueStoreId': store_id,
        'exportedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
        'apiOrigin': ORIGIN, 'retrievalMode': 'authenticated-get-only',
        'startsActor': False, 'publishesExternally': False, 'originAttested': False,
        'datasetItemCountBefore': dataset['itemCount'], 'datasetItemCountAfter': final_dataset['itemCount'],
        'outputEventsEmitted': expected, 'rowsExported': len(rows), 'datasetPages': pages,
        'emptyTailConfirmed': True, 'stableMetadataAndOutput': True,
        'paginationHeadersChecked': ['offset', 'limit', 'count', 'total'],
        'files': {name: {'bytes': len(data), 'sha256': sha256(data)} for name, data in artifacts.items()},
        'limitations': ['Export completeness is not a company-scan quality decision.',
                        'File hashes do not authenticate later arbitrary files as cloud originals.',
                        'Unchanged item counts and metadata cannot detect every same-count concurrent dataset edit.']
    }
    artifacts['export-manifest.json'] = encoded(manifest)
    artifacts['EXPORT_READY'] = b'Complete raw export only. Run quality_handoff.py before use.\n'
    return commit_export(base, run_id, artifacts)


def preflight_handoff(out, run_id):
    identifier(run_id, 'Run ID')
    base = checked_base(out)
    for name in (run_id, run_id + '-handoff'):
        target = base / name
        if target.exists() or target.is_symlink():
            raise ExportError('Export or handoff destination already exists; choose a new private base')
    return base


def handoff_from_export(destination, token):
    """Classify frozen raw files, then exclusively commit private research artifacts."""
    try:
        import quality_handoff as quality
    except ImportError:
        raise ExportError('Quality handoff helper is unavailable') from None
    try:
        raw = checked_base(destination)
        identifier(raw.name, 'Run ID')
        base = checked_base(raw.parent)
        target = base / (raw.name + '-handoff')
        if target.exists() or target.is_symlink():
            raise ExportError('Handoff destination already exists')
        if not isinstance(token, str) or not token or token in str(target):
            raise ExportError('Handoff path or credential is invalid')
        credential = token.encode('utf-8')

        def frozen_file(name):
            file = raw / name
            if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_BYTES:
                raise ExportError('Raw export artifact is unavailable or unsafe')
            data = file.read_bytes()
            if len(data) > MAX_BYTES or credential in data:
                raise ExportError('Raw export artifact exceeds limits or contains credential data')
            return data

        manifest = strict_json(frozen_file('export-manifest.json'))
        if (not isinstance(manifest, dict) or manifest.get('runId') != raw.name
                or manifest.get('actorId') != ACTOR_ID
                or not isinstance(manifest.get('files'), dict)
                or set(manifest['files']) != {'run.json', 'OUTPUT.json', 'rows.json'}
                or frozen_file('EXPORT_READY') != b'Complete raw export only. Run quality_handoff.py before use.\n'):
            raise ExportError('Raw export manifest or completion marker is invalid')
        source = {}
        for name in ('run.json', 'OUTPUT.json', 'rows.json'):
            data = frozen_file(name)
            expected = manifest['files'][name]
            if (not isinstance(expected, dict) or type(expected.get('bytes')) is not int
                    or expected['bytes'] != len(data) or expected.get('sha256') != sha256(data)):
                raise ExportError('Raw export artifact no longer matches its manifest')
            source[name] = strict_json(data)
        # Do not use a replay clock: research freshness is evaluated now.
        result = quality.classify(source['run.json'], source['OUTPUT.json'], source['rows.json'])
        with tempfile.TemporaryDirectory(prefix='.' + raw.name + '-handoff-render-', dir=str(base)) as staging:
            rendered = pathlib.Path(staging) / 'artifacts'
            summary = quality.write_handoff(result, rendered)
            expected_names = {'ready.json', 'held.json', 'ready.csv', 'held.csv', 'summary.json', 'DONE'}
            if summary['readyRows']:
                expected_names.add('HANDOFF_READY')
            if (set(file.name for file in rendered.iterdir()) != expected_names
                    or any(file.is_symlink() or not file.is_file() for file in rendered.iterdir())):
                raise ExportError('Rendered handoff artifacts are incomplete or unsafe')
            artifacts = {name: (rendered / name).read_bytes() for name in expected_names}
            if any(len(data) > MAX_BYTES or credential in data for data in artifacts.values()):
                raise ExportError('Rendered handoff exceeds limits or contains credential data')
            handoff = commit_export(base, raw.name + '-handoff', artifacts)
        return handoff, summary
    except (quality.HandoffError, OSError, ValueError, TypeError, UnicodeError):
        raise ExportError('Quality handoff could not be completed') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True, help='One already completed Hiring Actor run ID')
    parser.add_argument('--out', required=True, help='Private base outside Git; a run-ID directory is created')
    parser.add_argument('--max-rows', type=int, default=100000)
    parser.add_argument('--page-size', type=int, default=1000)
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('--max-seconds', type=float, default=120)
    parser.add_argument('--handoff', action='store_true', help='Also classify private research JSON/CSV with the current clock')
    args = parser.parse_args(argv)
    try:
        if args.handoff:
            preflight_handoff(args.out, args.run_id)
        api = ApifyGET(token_from_environment(), timeout=args.timeout, max_seconds=args.max_seconds)
        destination = export_completed_run(api, args.run_id, args.out, max_rows=args.max_rows, page_size=args.page_size)
    except ExportError as error:
        print('Export stopped: ' + str(error), file=sys.stderr)
        return 1
    if args.handoff:
        print('Complete private export saved. No Actor was started; no rows were published.')
        try:
            handoff, summary = handoff_from_export(destination, api.token)
        except ExportError:
            print('Quality handoff stopped; complete raw export is retained. No research readiness was claimed.', file=sys.stderr)
            return 2
        print(json.dumps({key: summary[key] for key in ['status', 'sourceRows', 'readyRows', 'heldRows']}, ensure_ascii=False))
        print('Private handoff directory: ' + str(handoff))
        if summary['status'] in {'HELD_ONLY', 'EMPTY_HELD_SNAPSHOT'}:
            print('Quality handoff contains only held diagnostics; inspect its private summary before reuse.', file=sys.stderr)
            return 3
        return 0
    handoff = destination.parent / (args.run_id + '-handoff')
    command = ['python3', str(pathlib.Path(__file__).absolute().with_name('quality_handoff.py')),
               '--run', str(destination / 'run.json'), '--output', str(destination / 'OUTPUT.json'),
               '--rows', str(destination / 'rows.json'), '--out', str(handoff)]
    print('Complete private export saved. No Actor was started; no rows were published.')
    print('Next, classify completeness and freshness:')
    print(' '.join(shlex.quote(piece) for piece in command))
    return 0


if __name__ == '__main__':
    sys.exit(main())
