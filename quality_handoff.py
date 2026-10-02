#!/usr/bin/env python3
"""Offline Hiring Signals handoff. Never starts an Actor or publishes records."""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import tempfile

ACTOR_ID = 'ujkEG4gpQNbpYOQcc'
EVENTS = {'new', 'changed', 'reopened', 'closed', 'current'}
BAD_STOPS = {'limit_reached', 'source_pagination_limit', 'repeated_page',
             'budget_limited', 'retry_exhausted', 'request_failed', 'failed'}
CSV_FIELDS = ['companyId', 'companyName', 'jobId', 'eventType', 'title', 'location',
              'jobUrl', 'detectedAt', 'verificationStatus', 'safeToPublish',
              'reviewRequired', 'handoffDecision', 'handoffReasons', 'recordJson']
CSV_PREFIX_CONTROLS = ''.join(chr(number) for number in range(32))


class HandoffError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def integer(value, name):
    if type(value) is not int or value < 0:
        raise HandoffError(name + ' must be a non-negative integer')
    return value


def stamp(value, name):
    if not isinstance(value, str):
        raise HandoffError(name + ' must be an ISO timestamp')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise HandoffError(name + ' must include a timezone')
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError) as error:
        if isinstance(error, HandoffError):
            raise
        raise HandoffError(name + ' must be an ISO timestamp') from None


def identity(value):
    # LinkedIn IDs are exact strings; coercing booleans/numbers could join the wrong company.
    return value if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value) else None


def csv_cell(value):
    if value is None:
        return ''
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if text.lstrip(CSV_PREFIX_CONTROLS + ' \ufeff').startswith(('=', '+', '-', '@')) or (text and ord(text[0]) < 32):
        text = "'" + text
    # Non-printing C0 bytes such as NUL are not valid in some CSV readers.
    # Show their escapes in CSV; ready/held JSON preserves the original text.
    return ''.join('\\u%04x' % ord(char) if ord(char) < 32 and char not in '\t\r\n' else char for char in text)


def csv_bytes(rows):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        audit = row['_handoff']
        values = {field: row.get(field) for field in CSV_FIELDS}
        values.update(handoffDecision=audit['decision'],
                      handoffReasons=';'.join(audit['reasons']),
                      recordJson=json.dumps(row, ensure_ascii=False, separators=(',', ':')))
        writer.writerow({key: csv_cell(value) for key, value in values.items()})
    return out.getvalue().encode('utf-8')


def classify(run, output, rows, *, as_of=None, max_age_hours=24):
    if not isinstance(run, dict) or not isinstance(output, dict):
        raise HandoffError('run and OUTPUT must be objects')
    if run.get('actId') != ACTOR_ID or not isinstance(run.get('id'), str) or not run['id']:
        raise HandoffError('run must identify the Hiring Signals Actor and a run ID')
    if run.get('status') not in {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}:
        raise HandoffError('run must be in a terminal state')
    if not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(r, dict) for r in rows):
        raise HandoffError('rows must be a complete array of at most 100000 objects')
    if any('_handoff' in row for row in rows):
        raise HandoffError('source rows already contain handoff annotations')
    if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, (int, float)) or not 0 < max_age_hours <= 720:
        raise HandoffError('max_age_hours must be greater than 0 and at most 720')
    now = stamp(as_of, 'as_of') if as_of is not None else dt.datetime.now(dt.timezone.utc)
    start = stamp(run.get('startedAt'), 'run.startedAt')
    finish = stamp(run.get('finishedAt'), 'run.finishedAt')
    generated = stamp(output.get('generatedAt'), 'OUTPUT.generatedAt')
    slack = dt.timedelta(seconds=60)
    if finish < start or not start - slack <= generated <= finish + slack:
        raise HandoffError('OUTPUT time does not belong to the run window')
    if finish > now + slack:
        raise HandoffError('run snapshot is in the future')
    stale = now - finish > dt.timedelta(hours=max_age_hours)
    status = output.get('status')
    if status not in {'SUCCEEDED', 'SUCCEEDED_WITH_WARNINGS', 'FAILED_QUALITY_GATE'}:
        raise HandoffError('OUTPUT status is missing or unknown')
    if 'qualityError' not in output or (output['qualityError'] is not None and not isinstance(output['qualityError'], str)):
        raise HandoffError('OUTPUT.qualityError must be null or a string')
    expected = integer(output.get('eventsEmitted'), 'OUTPUT.eventsEmitted')
    if expected != len(rows):
        raise HandoffError('complete rows count must match OUTPUT.eventsEmitted')
    if not isinstance(output.get('scans'), list) or len(output['scans']) > 10000:
        raise HandoffError('OUTPUT.scans must be an array of at most 10000 scans')
    if any(not isinstance(scan, dict) for scan in output['scans']):
        raise HandoffError('OUTPUT.scans contains a non-object')
    integer(output.get('companiesRequested'), 'OUTPUT.companiesRequested')
    scanned = integer(output.get('companiesScanned'), 'OUTPUT.companiesScanned')
    if scanned != len(output['scans']) or scanned > output['companiesRequested']:
        raise HandoffError('company scan counts do not match OUTPUT.scans')
    if 'completeScans' in output:
        complete = integer(output['completeScans'], 'OUTPUT.completeScans')
        if complete != sum(scan.get('complete') is True for scan in output['scans']):
            raise HandoffError('complete scan count does not match scan markers')
    if 'incompleteScans' in output:
        incomplete = integer(output['incompleteScans'], 'OUTPUT.incompleteScans')
        if incomplete != sum(scan.get('complete') is not True for scan in output['scans']):
            raise HandoffError('incomplete scan count does not match scan markers')
    if 'eventsByType' in output:
        counts = output['eventsByType']
        if not isinstance(counts, dict) or set(counts) - EVENTS:
            raise HandoffError('OUTPUT.eventsByType contains unknown events')
        actual = collections.Counter(row.get('eventType') for row in rows)
        for event in EVENTS:
            if integer(counts.get(event, 0), 'event count') != actual[event]:
                raise HandoffError('event counts do not match the supplied rows')
    index = collections.defaultdict(list)
    for scan in output['scans']:
        key = identity(scan.get('companyId'))
        if key:
            index[key].append(scan)
    scan_issues = sum(
        not identity(scan.get('companyId'))
        or len(index.get(identity(scan.get('companyId')), [])) != 1
        or type(scan.get('complete')) is not bool
        or type(scan.get('usable')) is not bool
        or not scan.get('complete')
        or not scan.get('usable')
        or ('qualityFailed' in scan and type(scan['qualityFailed']) is not bool)
        or scan.get('qualityFailed', False)
        or not isinstance(scan.get('stopReason'), str)
        or not scan.get('stopReason')
        or scan.get('stopReason') in BAD_STOPS
        for scan in output['scans'])
    duplicates = collections.Counter((identity(row.get('companyId')), identity(row.get('jobId'))) for row in rows)
    run_reasons = []
    if run['status'] != 'SUCCEEDED':
        run_reasons.append('RUN_NOT_SUCCESSFUL')
    if status == 'FAILED_QUALITY_GATE' or output['qualityError'] is not None:
        run_reasons.append('RUN_QUALITY_GATE')
    if stale:
        run_reasons.append('STALE_SNAPSHOT')
    ready, held = [], []
    for row in rows:
        reasons = list(run_reasons)
        company, job = identity(row.get('companyId')), identity(row.get('jobId'))
        scan = None
        if not company or not job:
            reasons.append('INVALID_IDENTITY')
        matches = index.get(company, [])
        if not matches:
            reasons.append('UNKNOWN_COMPANY_SCAN')
        elif len(matches) != 1:
            reasons.append('DUPLICATE_COMPANY_SCAN')
        else:
            scan = matches[0]
            markers = [scan.get('complete'), scan.get('usable')]
            if any(type(marker) is not bool for marker in markers) or ('qualityFailed' in scan and type(scan['qualityFailed']) is not bool):
                reasons.append('INVALID_SCAN_MARKERS')
            elif not scan['complete'] or not scan['usable'] or scan.get('qualityFailed', False):
                reasons.append('INCOMPLETE_OR_UNUSABLE_SCAN')
            stop = scan.get('stopReason')
            if not isinstance(stop, str) or not stop:
                reasons.append('INVALID_STOP_REASON')
            elif stop in BAD_STOPS:
                reasons.append('INCOMPLETE_STOP_REASON')
        if row.get('eventType') not in EVENTS or row.get('source') != 'linkedin_public_jobs':
            reasons.append('INVALID_EVENT_CONTRACT')
        if duplicates[(company, job)] > 1:
            reasons.append('DUPLICATE_JOB_EVENT')
        try:
            detected = stamp(row.get('detectedAt'), 'row.detectedAt')
            if not start - slack <= detected <= finish + slack:
                reasons.append('ROW_OUTSIDE_RUN_WINDOW')
        except HandoffError:
            reasons.append('INVALID_EVENT_TIME')
        reasons = sorted(set(reasons))
        enriched = dict(row)
        enriched['_handoff'] = {
            'decision': 'HELD' if reasons else 'READY_FOR_RESEARCH',
            'reasons': reasons,
            'runId': run['id'],
            'sourceGeneratedAt': output['generatedAt'],
            'companyScanComplete': scan.get('complete') if scan else None,
            'companyScanUsable': scan.get('usable') if scan else None,
            'scanStopReason': scan.get('stopReason') if scan else None,
            'applicationRouteVerifiedByHandoff': False,
        }
        (held if reasons else ready).append(enriched)
    empty_reasons = list(run_reasons)
    if scan_issues:
        empty_reasons.append('INCOMPLETE_OR_INVALID_COMPANY_SCANS')
    result_status = ('READY_FOR_RESEARCH' if ready else 'HELD_ONLY' if held
                     else 'EMPTY_HELD_SNAPSHOT' if empty_reasons
                     else 'EMPTY_VALID_SNAPSHOT')
    return {
        'ready': ready, 'held': held,
        'summary': {
            'schemaVersion': '1.0', 'runId': run['id'], 'buildNumber': run.get('buildNumber'),
            'platformStatus': run['status'], 'applicationStatus': status,
            'sourceGeneratedAt': output['generatedAt'], 'evaluatedAt': now.isoformat(),
            'evaluationTimeMode': 'EXPLICIT' if as_of is not None else 'CURRENT_CLOCK',
            'maxAgeHours': max_age_hours, 'sourceRows': len(rows),
            'runLevelReasons': run_reasons, 'qualityError': output['qualityError'],
            'companyScans': len(output['scans']), 'companyScansWithQualityIssues': scan_issues,
            'emptySnapshotReasons': empty_reasons if not rows else [],
            'readyRows': len(ready), 'heldRows': len(held),
            'readyEventCounts': dict(collections.Counter(row['eventType'] for row in ready)),
            'heldReasonCounts': dict(collections.Counter(reason for row in held for reason in row['_handoff']['reasons'])),
            'status': result_status,
            'inputHashes': {'run': digest(run), 'output': digest(output), 'rows': digest(rows)},
            'startsActor': False, 'publishesExternally': False,
            'paidCustomerUseOrRevenueProven': False,
            'applicationRoutesVerifiedByHandoff': False,
            'originAttested': False,
            'truthBoundary': 'Complete-scanned source events for research; not verified application availability. Offline file checks do not attest API origin. Held observations remain diagnostics.',
        },
    }


def write_handoff(result, destination):
    destination = pathlib.Path(destination)
    if destination.is_symlink():
        raise HandoffError('destination must not be a symlink')
    files = {'ready.json': canonical(result['ready']) + b'\n',
             'held.json': canonical(result['held']) + b'\n',
             'ready.csv': csv_bytes(result['ready']), 'held.csv': csv_bytes(result['held'])}
    summary = dict(result['summary'])
    summary['artifactHashes'] = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files['DONE'] = b'Offline handoff artifacts complete.\n'
    if summary['readyRows']:
        files['HANDOFF_READY'] = b'Complete-scan research events only. Not an application-route verification.\n'
    if destination.exists():
        if not destination.is_dir():
            raise HandoffError('destination must be a directory')
        if any(artifact.is_symlink() for artifact in destination.iterdir()):
            raise HandoffError('destination artifacts must not be symlinks')
        # Re-evaluate freshness first. Reuse the original timestamp only for an
        # otherwise identical current-clock classification and intact artifacts.
        # Explicit dated replays retain their requested evaluation timestamp.
        try:
            previous = read_json(destination / 'summary.json')
        except (HandoffError, OSError, ValueError):
            previous = None
        if isinstance(previous, dict) and summary['evaluationTimeMode'] == previous.get('evaluationTimeMode') == 'CURRENT_CLOCK':
            old_without_time = {key: value for key, value in previous.items() if key != 'evaluatedAt'}
            new_without_time = {key: value for key, value in summary.items() if key != 'evaluatedAt'}
            if (canonical(old_without_time) == canonical(new_without_time)
                    and stamp(summary['evaluatedAt'], 'evaluatedAt') >= stamp(previous.get('evaluatedAt'), 'previous evaluatedAt')
                    and all((destination / name).is_file() and (destination / name).read_bytes() == data for name, data in files.items())):
                summary['evaluatedAt'] = previous['evaluatedAt']
        files['summary.json'] = canonical(summary) + b'\n'
        if not destination.is_dir() or any(not (destination / name).is_file() or (destination / name).read_bytes() != data for name, data in files.items()) or set(p.name for p in destination.iterdir()) != set(files):
            raise HandoffError('destination exists with different or incomplete artifacts; use a new directory')
        return summary
    files['summary.json'] = canonical(summary) + b'\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = pathlib.Path(tempfile.mkdtemp(prefix='.hiring-handoff-', dir=destination.parent))
    try:
        for name, data in files.items():
            with (staged / name).open('wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        os.rename(staged, destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return summary


def read_json(path):
    path = pathlib.Path(path)
    if path.stat().st_size > 50 * 1024 * 1024:
        raise HandoffError('input file exceeds 50 MiB')
    def reject_constant(value):
        raise HandoffError('non-finite JSON numbers are not allowed')
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise HandoffError('duplicate JSON object key')
            value[key] = item
        return value
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant, object_pairs_hook=unique_keys)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Saved run metadata JSON')
    parser.add_argument('--output', required=True, help='Saved OUTPUT JSON')
    parser.add_argument('--rows', required=True, help='Complete dataset array JSON')
    parser.add_argument('--out', required=True, help='New local artifact directory')
    parser.add_argument('--as-of', help='Explicit UTC evaluation time for dated replays')
    parser.add_argument('--max-age-hours', type=float, default=24)
    args = parser.parse_args()
    try:
        result = classify(read_json(args.run), read_json(args.output), read_json(args.rows),
                          as_of=args.as_of, max_age_hours=args.max_age_hours)
        summary = write_handoff(result, args.out)
    except (HandoffError, OSError, ValueError, TypeError) as error:
        parser.exit(2, 'Handoff stopped: ' + str(error) + '\n')
    print(json.dumps({key: summary[key] for key in ['runId', 'status', 'sourceRows', 'readyRows', 'heldRows', 'startsActor', 'publishesExternally']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
