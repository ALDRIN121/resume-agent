"""Real local app for browser acceptance; only model responses are substituted."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def build_app(root: Path, profile_mode: str):
    # This entrypoint also runs outside pytest. Isolate before application imports.
    for key in tuple(os.environ):
        if (key.startswith(('RESUME_GENERATOR_', 'LITELLM_'))
                or key.endswith(('_API_KEY', '_API_TOKEN', '_BASE_URL'))
                or key in {'ANTHROPIC_AUTH_TOKEN', 'OPENAI_ACCESS_TOKEN', 'OPENAI_API_BASE',
                           'GOOGLE_APPLICATION_CREDENTIALS', 'AWS_ACCESS_KEY_ID',
                           'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN'}):
            os.environ.pop(key)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ['RESUME_GENERATOR_STATE_DIR'] = str(root)
    os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
    # Deliberately fictional; global settings endpoints share this isolated root.
    (root / '.env').write_text('OPENAI_API_KEY=fixture-only\n', encoding='utf-8')

    from resume_agent.api.app import create_app
    from resume_agent.config import FeaturesConfig, ModelConfig, OutputConfig, ResumeAgentSettings
    from resume_agent.contracts import content_hash
    from resume_agent.runtime import Runtime
    from resume_agent.schemas import UserResume

    profile = UserResume.model_validate({
        'personal': {'full_name': 'Casey Example', 'email': 'casey@example.invalid'},
        'summary': 'Engineer who helped maintain reliable systems.',
        'experience': [{
            'company': 'Example Works', 'title': 'Engineer', 'start': '2022', 'end': '2025',
            'bullets': ['Helped reduce latency from 450ms to 90ms; preserved -- and +80%.'],
        }],
        'skills': {'Languages': ['Python', 'C++']},
    })

    async def model(stage, schema, messages):
        with (root / 'model-calls.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': stage, 'schema': schema.__name__}) + '\n')
        if stage == 'import_profile':
            return profile.model_dump(mode='json')
        if stage == 'role_evaluation':
            fixed = json.loads(messages[-1]['content'])
            text = fixed['job']['text']
            unknown = 'CASE_UNKNOWN' in text
            start = text.index('Python')
            response = {'requirements': [{'id': 'skills', 'dimension': 'required_skills', 'operator': 'single',
                'members': [{'id': 'python', 'text': 'Python', 'citations': [{'start': start, 'end': start + 6, 'quote': 'Python'}]}]}],
                'findings': [{'member_id': 'python', 'status': 'unknown' if unknown else 'supported',
                    'rationale': 'Evidence is unspecified.' if unknown else 'The reviewed profile lists Python.',
                    'sources': [] if unknown else [{'kind': 'profile', 'input_hash': fixed['profile_revision'],
                        'target_path': '/skills/Languages/0', 'quote': 'Python'}]}], 'eligibility': []}
            if 'CASE_INELIGIBLE' in text:
                quote = 'No visa sponsorship.'
                position = text.index(quote)
                statement = fixed['eligibility_facts'].get('authorization')
                response['eligibility'] = [{'category': 'authorization', 'status': 'fail' if statement else 'unknown',
                    'rationale': 'Compare the explicit posting restriction and supplied sponsorship statement.',
                    'citation': {'start': position, 'end': position + len(quote), 'quote': quote},
                    'sources': [{'kind': 'eligibility', 'input_hash': content_hash(fixed['eligibility_facts']),
                        'target_path': '/authorization', 'quote': statement}] if statement else []}]
            return response
        if stage == 'extract_jd':
            return {'company': 'Example QA', 'role_title': 'Reliability Engineer'}
        if stage == 'questions':
            return {'questions': [{'id': 'q1', 'prompt': 'What should remain unchanged?',
                                   'why_asking': 'Confirm the supplied contribution scope.'}]}
        if stage == 'proposals':
            return {'proposals': [{
                'id': 'p1', 'operation': 'replace', 'target_path': '/summary',
                'source_revision': content_hash(profile),
                'before_hash': content_hash(profile.summary),
                'after': 'This summary must remain unselected in the reject-all journey.',
                'source_refs': [{'kind': 'profile', 'input_hash': content_hash(profile),
                                 'target_path': '/summary'}],
                'rationale': 'An explicit optional rewrite.',
            }]}
        raise AssertionError(f'Unexpected model stage: {stage}')

    settings = ResumeAgentSettings(_env_file=None, provider='openai', openai_api_key='fixture-only',
        model=ModelConfig(default='fixture-structured'),
        features=FeaturesConfig(enable_hr_review=False), output=OutputConfig(base_dir=str(root / 'output')))
    settings.save()
    # Actual deterministic template, compiler, page rendering, guard and export.
    services = Runtime(root=root, settings=settings, model=model)
    # Only the external board boundary is replaced; all HTTP/API/storage stay real.
    import httpx
    from resume_agent.discovery.http import BoundedHttpClient
    async def board_feed(request):
        import asyncio
        path = root / 'discovery-feed.json'
        fixture = json.loads(path.read_text()) if path.exists() else {'payload': {'jobs': [], 'meta': {'total': 0}}}
        await asyncio.sleep(fixture.get('delay', 0))
        return httpx.Response(fixture.get('status', 200), headers={'content-type': 'application/json'},
                              stream=httpx.ByteStream(json.dumps(fixture.get('payload', {})).encode()))
    async def no_retry_wait(delay):
        pass
    services.discovery.http_factory = lambda: BoundedHttpClient(transport=httpx.MockTransport(board_feed), validator=lambda _: None)
    services.discovery.sleep = no_retry_wait
    if profile_mode != 'missing' and services.profiles.load_snapshot() is None:
        original = profile
        if profile_mode == 'old':
            original = profile.model_copy(deep=True, update={'personal': profile.personal.model_copy(
                update={'full_name': 'Previous Candidate'})})
        services.profiles.save_reviewed(None, original, {'source': 'fictional browser fixture'})
    return create_app(services=services)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--profile', choices=['ready', 'old', 'missing'], default='ready')
    options = parser.parse_args()
    app = build_app(options.root, options.profile)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=options.port, log_level='warning')


if __name__ == '__main__':
    main()
