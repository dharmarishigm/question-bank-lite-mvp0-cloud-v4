"""Add reviewed program presets through the admin API without overwriting edits.

Run with the existing gcloud admin identity; credentials stay in memory.
Dry run (default) validates local presets. --apply creates missing programs and
setups, checks full/subject prompts, and writes a non-secret JSON receipt.
Never generates questions, publishes exams, or restores archived programs.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def command(args):
    result = subprocess.run(['gcloud', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('GCP configuration lookup failed')
    return result.stdout.strip()


def presets():
    import app  # Initialise the existing application model registrations.
    from blueprint_domain import ProgramInput
    from program_exam import Settings, ready
    values = []
    for path in sorted((ROOT / 'program_presets').glob('*.json')):
        data = json.loads(path.read_text())
        ProgramInput.model_validate(data['program'])
        settings = Settings.model_validate(data['settings'])
        ready(settings)
        assert settings.mode == 'FULL' and settings.reuse_questions
        for section in settings.sections:
            ready(Settings.model_validate({**data['settings'], 'mode': 'SUBJECT', 'sections': [section.model_dump()]}))
        values.append(data)
    if not values:
        raise RuntimeError('No presets found')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--base-url', default='https://meritiqra.com')
    parser.add_argument('--receipt', type=Path, default=ROOT / 'docs/validation/competitive-programs-deployment.json')
    args = parser.parse_args()
    catalog = presets()
    if not args.apply:
        print(f'Validated {len(catalog)} full and subject-wise presets; no remote writes.')
        return
    project, service, region = 'gen-lang-client-0491787004', 'question-bank-cloud-v4', 'asia-south1'
    config = json.loads(command(['run', 'services', 'describe', service, '--project='+project, '--region='+region, '--format=json']))
    base = args.base_url.rstrip('/')
    allowed = {'https://meritiqra.com', config['status']['url'].rstrip('/')}
    if base not in allowed:
        raise RuntimeError('Unrecognized application origin')
    env = {entry['name']: entry for entry in config['spec']['template']['spec']['containers'][0]['env']}

    def credential(name):
        entry = env[name]
        if 'value' in entry:
            return entry['value']
        ref = entry['valueFrom']['secretKeyRef']
        return command(['secrets', 'versions', 'access', ref['key'], '--secret='+ref['name'], '--project='+project])

    report = {'base_url': base, 'programs': [], 'questions_generated': 0, 'exams_published': 0}
    with httpx.Client(base_url=base, timeout=60) as client:
        client.get('/healthz').raise_for_status()
        response = client.post('/api/auth/admin-login', json={'email': credential('ADMIN_LOCAL_EMAIL'), 'password': credential('ADMIN_LOCAL_PASSWORD')})
        response.raise_for_status()
        client.headers['X-CSRF-Token'] = client.cookies['qb_csrf']
        try:
            for data in catalog:
                program, settings = data['program'], data['settings']
                response = client.get('/api/programs', params={'q': program['code'], 'limit': 100})
                response.raise_for_status()
                existing = next((p for p in response.json()['items'] if p['code'] == program['code']), None)
                if existing is None:
                    response = client.post('/api/programs', json=program)
                    response.raise_for_status()
                    existing = response.json()
                if existing['status'] != 'ACTIVE' or existing['name'] != program['name']:
                    raise RuntimeError(f"Existing program needs manual review: {program['code']}")
                pid = existing['id']
                response = client.get(f'/api/programs/{pid}/exam-setup')
                response.raise_for_status()
                saved = response.json()
                if saved and saved['settings'] != settings:
                    raise RuntimeError(f"Preserving edited setup for {program['code']}; no overwrite performed")
                if not saved:
                    response = client.put(f'/api/programs/{pid}/exam-setup', json={'settings': settings, 'revision': 0})
                    response.raise_for_status()
                response = client.get(f'/api/programs/{pid}/exam-setup')
                response.raise_for_status()
                assert response.json()['settings'] == settings
                variants = [settings] + [{**settings, 'mode': 'SUBJECT', 'sections': [s], 'duration_minutes': s['duration_minutes'] or settings['duration_minutes']} for s in settings['sections']]
                for variant in variants:
                    response = client.post(f'/api/programs/{pid}/exam-prompt', json=variant)
                    response.raise_for_status()
                    result = response.json()
                    assert result['question_count'] == sum(s['count'] for s in variant['sections'])
                    assert abs(result['total_marks'] - sum(s['count']*s['marks'] for s in variant['sections'])) < .0001
                    assert '| Subject |' in result['effective_prompt']
                    if variant['mode'] == 'SUBJECT':
                        assert '**Paper type:** Subject-wise' in result['effective_prompt']
                report['programs'].append({'id': pid, 'code': program['code'], 'name': program['name'], 'status': 'ACTIVE', 'questions': sum(s['count'] for s in settings['sections']), 'marks': sum(s['count']*s['marks'] for s in settings['sections']), 'duration_minutes': settings['duration_minutes'], 'sections': [s['subject'] for s in settings['sections']], 'full_and_all_subject_prompts_verified': True, 'saved_setup_verified': True, 'sources': data['sources']})
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(json.dumps(report, indent=2)+'\n')
                print(f"Ready: {program['name']} (#{pid})", flush=True)
        finally:
            client.post('/api/auth/logout')


if __name__ == '__main__':
    main()
