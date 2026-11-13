"""Official list endpoints and declared full-text extraction; no model calls."""
from html import unescape
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from ..config import MAX_JD_TEXT_CHARS
from ..contracts import content_hash
from .schemas import BoardResult, DiscoveredJob, DiscoveryError


def board_url(source, *, skip=0, limit=100):
    if source.provider == 'greenhouse':
        return f'https://boards-api.greenhouse.io/v1/boards/{source.board}/jobs?content=true'
    if source.provider == 'ashby':
        return f'https://api.ashbyhq.com/posting-api/job-board/{source.board}?includeCompensation=true'
    host = 'api.eu.lever.co' if source.region == 'eu' else 'api.lever.co'
    return f'https://{host}/v0/postings/{source.board}?' + urlencode({'mode': 'json', 'skip': skip, 'limit': limit})


def _required(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('missing_required_posting_text')
    return value


def _html(value):
    value = _required(value)
    # The original record is retained. This declared extraction handles encoded
    # HTML; it never edits or normalizes candidate wording.
    soup = BeautifulSoup(unescape(value), 'html.parser')
    return soup.get_text(separator='\n', strip=False).strip()


def _plain_or_html(raw, plain, html):
    if isinstance(raw.get(plain), str) and raw[plain].strip():
        return raw[plain]
    return _html(raw.get(html))


def _human(value, *, depth=0):
    if depth > 20:
        raise ValueError('posting_metadata_too_deep')
    if isinstance(value, dict):
        return '\n'.join(key.replace('_', ' ') + ': ' + _human(item, depth=depth + 1) for key, item in value.items())
    if isinstance(value, list):
        return '\n'.join(_human(item, depth=depth + 1) for item in value)
    return 'Not provided' if value is None else str(value)


def _url(value):
    value = _required(value)
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('invalid_posting_source_url')
    return value


def _identity(raw, provider):
    if not isinstance(raw, dict):
        raise ValueError('posting_object_required')
    value = raw.get('jobUrl') if provider == 'ashby' else raw.get('id')
    if provider == 'greenhouse' and type(value) is int and value > 0:
        return str(value)
    return _url(value) if provider == 'ashby' else _required(value)


def _record(raw, source):
    def duplicates(value, depth=0):
        if depth > 20:
            raise ValueError('posting_metadata_too_deep')
        if getattr(value, 'duplicate_keys', False):
            return True
        return any(duplicates(item, depth + 1) for item in (value.values() if isinstance(value, dict) else value)) if isinstance(value, (dict, list)) else False
    if duplicates(raw):
        raise ValueError('duplicate_json_record_keys')
    identity = _identity(raw, source.provider)
    if source.provider == 'ashby':
        if type(raw.get('isListed')) is not bool:
            raise ValueError('ashby_listed_flag_required')
        if not raw['isListed']:
            return identity, None
    title = _required(raw.get('text' if source.provider == 'lever' else 'title'))
    lines = [title]
    if source.company:
        lines.append('Company: ' + source.company)
    if source.provider == 'greenhouse':
        for key in ('location', 'departments', 'offices', 'metadata'):
            if raw.get(key) is not None:
                lines.append(key.capitalize() + ': ' + _human(raw[key]))
        lines.append(_required(_html(raw.get('content'))))
        url = _url(raw.get('absolute_url'))
    elif source.provider == 'lever':
        for key in ('categories', 'country', 'workplaceType', 'salaryRange'):
            if raw.get(key) is not None:
                lines.append(key + ': ' + _human(raw[key]))
        lines.append(_required(_plain_or_html(raw, 'descriptionPlain', 'description')))
        lists = raw.get('lists', [])
        if not isinstance(lists, list):
            raise ValueError('lever_lists_invalid')
        for section in lists:
            lines.append(_required(section['text']) + ':\n' + _html(section['content']))
        for plain, html in (('additionalPlain', 'additional'), ('salaryDescriptionPlain', 'salaryDescription')):
            if raw.get(plain) or raw.get(html):
                lines.append(_plain_or_html(raw, plain, html))
        url = _url(raw.get('hostedUrl'))
    else:
        for key in ('location', 'secondaryLocations', 'department', 'team', 'workplaceType', 'employmentType', 'compensation'):
            if raw.get(key) is not None:
                lines.append(key + ': ' + _human(raw[key]))
        lines.append(_required(_plain_or_html(raw, 'descriptionPlain', 'descriptionHtml')))
        url = _url(raw.get('jobUrl'))
    text = '\n\n'.join(lines)
    if not text.strip() or len(text) > MAX_JD_TEXT_CHARS:
        raise ValueError('posting_text_exceeds_supported_limit')
    return identity, DiscoveredJob(external_id=identity, title=title, text=text, source_url=url,
                                   raw=raw, raw_hash=content_hash(raw))


async def fetch_board(source, fetch_json, *, max_jobs=1000):
    """Keep valid rows, make every ambiguity partial, and never infer removals."""
    if not 1 <= max_jobs <= 1000:
        raise ValueError('invalid_discovery_job_limit')
    jobs, seen, conflicts = {}, {}, set()
    received = examined = malformed = duplicate = truncated = filtered = 0
    diagnostics, limit_reached, successful_page, fetch_failed = [], False, False, False
    skip = 0
    while True:
        limit = min(100, max_jobs - examined)
        try:
            payload = await fetch_json(board_url(source, skip=skip, limit=limit))
            if source.provider == 'lever':
                records = payload
            elif isinstance(payload, dict):
                records = payload.get('jobs')
                if source.provider == 'ashby' and payload.get('apiVersion', '1') != '1':
                    diagnostics.append('unsupported_ashby_api_version')
            else:
                records = None
            if not isinstance(records, list):
                raise DiscoveryError('invalid_provider_payload')
        except DiscoveryError as exc:
            diagnostics.append(exc.code)
            fetch_failed = not exc.partial
            limit_reached = limit_reached or exc.partial
            break
        successful_page = True
        received += len(records)
        if source.provider == 'greenhouse' and 'meta' in payload:
            total = payload['meta'].get('total') if isinstance(payload['meta'], dict) else None
            if type(total) is not int or total != len(records):
                diagnostics.append('provider_total_mismatch')
        remaining = max_jobs - examined
        if len(records) > remaining:
            truncated += len(records) - remaining
            limit_reached = True
        for raw in records[:remaining]:
            examined += 1
            try:
                identity = _identity(raw, source.provider)
                raw_hash = content_hash(raw)
                repeated = identity in seen
                if repeated:
                    duplicate += 1
                    if seen[identity] != raw_hash:
                        conflicts.add(identity)
                        jobs.pop(identity, None)
                else:
                    seen[identity] = raw_hash
                identity, job = _record(raw, source)
                if job is None:
                    filtered += 1
                elif not repeated and identity not in conflicts:
                    jobs[identity] = job
            except (ValueError, KeyError, TypeError, RecursionError):
                malformed += 1
        if source.provider != 'lever':
            break
        if len(records) > limit:
            diagnostics.append('unexpected_pagination_page_size')
            break
        if len(records) < limit:
            break
        if examined >= max_jobs:
            limit_reached = True
            break
        skip += limit
    if malformed:
        diagnostics.append('malformed_postings')
    if duplicate:
        diagnostics.append('duplicate_external_ids')
    if conflicts:
        diagnostics.append('conflicting_external_ids')
    if limit_reached:
        diagnostics.append('record_limit_reached')
    status = 'failed' if fetch_failed and not successful_page else 'partial' if diagnostics else 'complete'
    return BoardResult(status=status, jobs=list(jobs.values()), received_count=received, valid_count=len(jobs),
        malformed_count=malformed, duplicate_count=duplicate, conflicting_count=len(conflicts), truncated_count=truncated,
        filtered_count=filtered, limit_reached=limit_reached, diagnostics=list(dict.fromkeys(diagnostics)))
