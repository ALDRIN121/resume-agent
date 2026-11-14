"""Local descriptive outcomes from explicit events and immutable submission scores."""
from collections import Counter
from datetime import datetime
from fractions import Fraction
from typing import Literal

from .contracts import Contract, utc_now


class OutcomeBandReport(Contract):
    band: Literal['0–39', '40–69', '70–100']
    positive: int = 0
    negative: int = 0
    pending: int = 0
    withdrawn: int = 0
    closed_unclassified: int = 0
    resolved: int = 0
    positive_rate: float | None = None
    rate_suppressed: bool = True


class OutcomeReport(Contract):
    schema_version: Literal[1] = 1
    generated_at: str
    rubric_version: Literal['fit-v1'] = 'fit-v1'
    minimum_resolved: Literal[10] = 10
    rate_rounding: str = 'Percentage, nearest 0.01, half up'
    bands: list[OutcomeBandReport]
    counts: dict[str, int]
    exclusions: dict[str, int]
    unique_excluded: int
    description: str = 'Local descriptive evidence. These observations do not establish causation or a hiring probability.'


def classify_outcome(application):
    payloads = [event['payload'] for event in application['effective_events']]
    if any((p['kind'] == 'response_received' and p['category'] == 'favorable') or
           (p['kind'] in ('stage_change', 'reopen') and p['stage'] in ('screening', 'interviewing', 'offer')) for p in payloads):
        return 'positive'
    if any((p['kind'] == 'response_received' and p['category'] == 'rejection') or
           (p['kind'] == 'stage_change' and (p['stage'] == 'rejected' or
            (p['stage'] == 'closed' and p.get('closure_without_response', False)))) for p in payloads):
        return 'negative'
    return 'withdrawn' if application['stage'] == 'withdrawn' else 'closed_unclassified' if application['stage'] == 'closed' else 'pending'


def _percentage(positive, denominator):
    if not denominator:
        return None
    cents = Fraction(positive * 10000, denominator)
    rounded = (2 * cents.numerator + cents.denominator) // (2 * cents.denominator)
    return rounded / 100


def _lower(evaluation):
    raw = evaluation.get('lower_exact') if evaluation else None
    if not isinstance(raw, list) or len(raw) != 2 or any(type(n) is not int for n in raw) or raw[1] <= 0:
        return None
    value = Fraction(*raw)
    return value if 0 <= value <= 100 else None


def make_report(applications, *, generated_at=None):
    names = ('positive', 'negative', 'pending', 'withdrawn', 'closed_unclassified')
    bands = [dict(band=label, **dict.fromkeys(names, 0)) for label in ('0–39', '40–69', '70–100')]
    counts = dict.fromkeys(('total_applications', 'submitted', *names, 'unknown_score', 'unsupported_rubric', 'without_submission'), 0)
    exclusions = dict.fromkeys(('without_submission', 'unknown_score', 'unsupported_rubric', 'pending_known_score',
                                'withdrawn_known_score', 'closed_unclassified_known_score'), 0)
    for application in applications:
        counts['total_applications'] += 1
        submission = application['submission']
        if submission is None:
            counts['without_submission'] += 1
            exclusions['without_submission'] += 1
            continue
        counts['submitted'] += 1
        outcome = classify_outcome(application)
        counts[outcome] += 1
        evaluation = submission.get('evaluation')
        lower = _lower(evaluation)
        if lower is None:
            counts['unknown_score'] += 1
            exclusions['unknown_score'] += 1
            continue
        if evaluation.get('rubric_version') != 'fit-v1':
            counts['unsupported_rubric'] += 1
            exclusions['unsupported_rubric'] += 1
            continue
        band = bands[0 if lower < 40 else 1 if lower < 70 else 2]
        band[outcome] += 1
        if outcome not in ('positive', 'negative'):
            exclusions[outcome + '_known_score'] += 1
    for band in bands:
        resolved = band['positive'] + band['negative']
        band.update(resolved=resolved, positive_rate=_percentage(band['positive'], resolved) if resolved >= 10 else None,
                    rate_suppressed=resolved < 10)
    return OutcomeReport(generated_at=generated_at or utc_now(), bands=[OutcomeBandReport(**b) for b in bands],
                         counts=counts, exclusions=exclusions, unique_excluded=sum(exclusions.values())).model_dump(mode='json')


def generation_health(runs):
    counts = Counter(run.get('status', 'unknown') for run in runs)
    completed, failed = counts['complete'], counts['failed']
    return {'total': len(runs), 'completed': completed, 'failed': failed, 'cancelled': counts['cancelled'],
            'active': sum(counts[s] for s in ('queued', 'running', 'retrying', 'awaiting-input', 'interrupted')),
            'needs_input': counts['awaiting-input'] + counts['interrupted'], 'denominator': completed + failed,
            'percent': _percentage(completed, completed + failed)}


def _timestamp(value):
    if isinstance(value, (int, float)):
        return value
    try:
        return datetime.fromisoformat(value).timestamp() if value else None
    except (TypeError, ValueError):
        return None


def company_metrics(runs, jobs, applications):
    companies, company_runs = {}, {}

    def company(name, timestamp):
        name = name or 'Unknown'
        entry = companies.setdefault(name, {'name': name, 'total': 0, 'final': 0, 'needs': 0, 'failed': 0, 'cancelled': 0,
            'jobs': 0, 'applications': 0, 'submitted': 0, 'positive': 0, 'responses': 0, 'last_updated': None,
            'latest_run_id': None, 'latest_job_id': None, 'latest_application_id': None, 'unknown_company': name == 'Unknown'})
        observed = _timestamp(timestamp)
        if observed is not None:
            entry['last_updated'] = max(entry['last_updated'] or 0, observed)
        return entry

    for run in runs:
        entry = company(run.get('company'), run.get('created_at'))
        entry['latest_run_id'] = entry['latest_run_id'] or run.get('id') or run.get('thread_id')
        entry['total'] += 1
        entry['final'] += run['status'] == 'complete'
        entry['needs'] += run['status'] in ('awaiting-input', 'interrupted')
        entry['failed'] += run['status'] == 'failed'
        entry['cancelled'] += run['status'] == 'cancelled'
        company_runs.setdefault(entry['name'], []).append(run)
    for job in jobs:
        job = job.model_dump(mode='json') if hasattr(job, 'model_dump') else job
        entry = company(job.get('company'), job.get('captured_at'))
        entry['latest_job_id'] = entry['latest_job_id'] or job['id']
        entry['jobs'] += 1
    for application in applications:
        entry = company(application.get('company'), application.get('created_at'))
        entry['latest_application_id'] = entry['latest_application_id'] or application['id']
        entry['applications'] += 1
        entry['submitted'] += application['submission'] is not None
        entry['positive'] += application['submission'] is not None and classify_outcome(application) == 'positive'
        entry['responses'] += any(e['payload']['kind'] == 'response_received' for e in application['effective_events'])
    for entry in companies.values():
        entry['generation_health'] = generation_health(company_runs.get(entry['name'], []))
    return sorted(companies.values(), key=lambda c: (-(c['last_updated'] or 0), c['name']))


def metrics(runs, jobs, applications):
    report = make_report(applications)
    companies = company_metrics(runs, jobs, applications)
    return {'generation': generation_health(runs), 'jobs': len(jobs), 'companies': sum(not c['unknown_company'] for c in companies),
            'applications': {'recorded': len(applications), **report['counts']}, 'outcome_exclusions': report['exclusions']}


class OutcomeService:
    def __init__(self, applications):
        self.applications = applications

    def report(self):
        return make_report(self.applications.list())
