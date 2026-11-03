#!/usr/bin/env python3
"""Finalize static artifacts with hosting-tool evidence; no automated browser QA.

Checks hashes and a supplied release result. Never opens a browser, publishes files,
or claims to have tested interactive behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from archive_common import load, save

CHECKS = ()  # Compatibility for old integrations; no browser checks are a gate.


def make_receipt(run_dir, status, url='', release_status='', evidence='', reason=''):
    report = load(Path(run_dir)/'run-report.json', {})
    artifacts = report.get('artifacts', [])
    if status == 'deployed' and len(artifacts) != 1:
        raise ValueError('For multiple skins supply --receipt with individual release URLs')
    return {'artifacts': [
        {'html': a['html'], 'sha256': a['sha256'], 'deployment': {
            'status': status, 'url': url, 'release_status': release_status,
            'evidence': evidence, 'reason': reason}}
        for a in artifacts]}


def finalize(run_dir, receipt):
    run_dir = Path(run_dir).resolve()
    report = load(run_dir/'run-report.json')
    if not isinstance(report, dict) or not report.get('build_ok',report.get('ok')) or not report.get('artifacts'):
        raise ValueError('A successful local static build report is required')
    rows = receipt.get('artifacts')
    if not isinstance(rows, list) or len(rows) != len(report['artifacts']):
        raise ValueError('receipt.artifacts must cover each built artifact exactly once')
    local_only = load(Path(report['source'])/'project_meta.json').get('presentation', {}).get('local_only') is True
    delivered = []
    for artifact in report['artifacts']:
        path = Path(artifact['html']).resolve()
        if artifact.get('contract_verified') is not True:
            raise ValueError('Artifact needs a passing static contract: ' + str(path))
        matches = [r for r in rows if isinstance(r, dict) and r.get('html') == str(path)]
        if len(matches) != 1: raise ValueError('Missing or duplicate receipt: ' + str(path))
        row = matches[0]
        current_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if current_sha != artifact.get('sha256'):
            raise ValueError('HTML changed after the verified build: ' + str(path))
        if row.get('sha256') != current_sha:
            raise ValueError('Receipt belongs to a different HTML: ' + str(path))
        deployment = row.get('deployment', {})
        status = deployment.get('status') if isinstance(deployment, dict) else None
        if status == 'deployed':
            url = deployment.get('url', '')
            parsed = urlsplit(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme != 'https' or not parsed.netloc or not deployment.get('evidence') or deployment.get('release_status') != 'finished':
                raise ValueError('deployed needs final HTTPS URL, tool evidence and release_status=finished')
            delivered.append({'type': 'url', 'value': url})
        elif status in ('failed', 'unavailable'):
            if not deployment.get('reason') or not deployment.get('evidence'):
                raise ValueError('HTML fallback requires deployment failure/unavailability evidence and reason')
            delivered.append({'type': 'html', 'value': str(path), 'reason': deployment['reason']})
        elif status == 'local_only' and local_only:
            delivered.append({'type': 'html', 'value': str(path), 'reason': 'user_requested_local_only'})
        else:
            raise ValueError('Deployment is pending; default delivery cannot skip the attempt')
    report['browser_qa_required'] = False
    report['build_ok'] = True
    report['ok'] = True
    report['delivery_complete'] = True
    report['status'] = 'complete'
    report['browser_interactions_verified'] = False
    report['live_deployment_verified'] = all(v['type'] == 'url' for v in delivered)
    report['delivery'] = {
        'status': 'complete', 'artifacts': delivered,
        'verification_basis': 'static_contract_and_hosting_tool',
        'browser_qa': 'not_requested', 'online_browser_qa': 'not_requested'}
    save(run_dir/'delivery-receipt.json', receipt)
    save(run_dir/'run-report.json', report)
    return report['delivery']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument('--receipt', type=Path)
    options.add_argument('--status', choices=('deployed', 'failed', 'unavailable', 'local_only'))
    parser.add_argument('--url', default='')
    parser.add_argument('--release-status', default='')
    parser.add_argument('--evidence', default='')
    parser.add_argument('--reason', default='')
    args = parser.parse_args()
    receipt = load(args.receipt) if args.receipt else make_receipt(
        args.run_dir, args.status, args.url, args.release_status, args.evidence, args.reason)
    print(json.dumps(finalize(args.run_dir, receipt), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (ValueError, TypeError, KeyError, OSError) as exc: raise SystemExit(str(exc))
