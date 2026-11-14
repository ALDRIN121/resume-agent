"""Bounded single GET attempts. Retry consumption belongs to the durable journal."""
from __future__ import annotations

import asyncio
import json
import math
import time
import zlib
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from ..contracts import utc_now
from ..tools.scrape import _validate_url
from .schemas import DiscoveryError

HOSTS = frozenset(('boards-api.greenhouse.io', 'api.lever.co', 'api.eu.lever.co', 'api.ashbyhq.com'))


class DiscoveryRequestError(DiscoveryError):
    def __init__(self, code, *, transient=False, retry_after=None, status_code=None, partial=False):
        super().__init__(code, partial=partial)
        self.transient, self.retry_after, self.status_code = transient, retry_after, status_code


@dataclass(frozen=True)
class ResponseReceipt:
    body: bytes
    url: str
    status_code: int
    headers: dict[str, str]
    observed_at: str
    physical_requests: int


class _JSONObject(dict):
    duplicate_keys = False


def _object(pairs):
    value = _JSONObject()
    for key, item in pairs:
        if key in value:
            value.duplicate_keys = True
        value[key] = item
    return value


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('nonfinite_json_number')
    return result


def _constant(value):
    raise ValueError('nonfinite_json_constant')


def decode_json(body):
    value = json.loads(body.decode('utf-8'), object_pairs_hook=_object, parse_float=_number, parse_constant=_constant)
    if getattr(value, 'duplicate_keys', False):
        raise ValueError('duplicate_top_level_json_keys')
    return value


def retry_after(value, now):
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            delay = (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, delay) if math.isfinite(delay) else None


def _safe_url(url, original_host):
    parsed = urlsplit(url)
    try:
        safe = (parsed.scheme == 'https' and parsed.hostname in HOSTS and parsed.hostname == original_host
                and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment)
    except ValueError:
        safe = False
    if not safe:
        raise DiscoveryRequestError('redirect_host_rejected')


class BoundedHttpClient:
    def __init__(self, *, transport=None, validator=_validate_url, timeout=20, max_bytes=10 * 1024 * 1024,
                 clock=time.time):
        if not 0 < timeout <= 20 or not 0 < max_bytes <= 10 * 1024 * 1024:
            raise ValueError('invalid_discovery_transport_limits')
        self.transport, self.validator, self.timeout, self.max_bytes, self.clock = transport, validator, timeout, max_bytes, clock
        self.semaphore = asyncio.Semaphore(3)
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(transport=self.transport, follow_redirects=False, timeout=self.timeout,
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=3),
            headers={'Accept': 'application/json', 'Accept-Encoding': 'gzip, deflate', 'User-Agent': 'Resume-Agent-Public-Discovery/1'})
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def _body(self, response):
        encoding = response.headers.get('content-encoding', 'identity').lower().strip()
        if encoding not in ('identity', '', 'gzip', 'deflate'):
            raise DiscoveryRequestError('unsupported_content_encoding')
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS) if encoding in ('gzip', 'deflate') else None
        chunks, decoded, wire = [], 0, 0
        async for raw in response.aiter_raw(chunk_size=65536):
            wire += len(raw)
            if wire > self.max_bytes:
                raise DiscoveryRequestError('response_body_limit', partial=True)
            data = decoder.decompress(raw, self.max_bytes - decoded + 1) if decoder else raw
            decoded += len(data)
            if decoded > self.max_bytes or (decoder and decoder.unconsumed_tail):
                raise DiscoveryRequestError('response_body_limit', partial=True)
            chunks.append(data)
        if decoder and (not decoder.eof or decoder.unused_data):
            raise DiscoveryRequestError('invalid_content_encoding')
        return b''.join(chunks)

    async def fetch_once(self, url):
        if self.client is None:
            raise RuntimeError('discovery_client_context_required')
        host = urlsplit(url).hostname
        current = url
        async with self.semaphore:
            try:
                async with asyncio.timeout(self.timeout):
                    for hop in range(6):
                        _safe_url(current, host)
                        try:
                            await asyncio.to_thread(self.validator, current)
                        except ValueError:
                            raise DiscoveryRequestError('public_address_rejected') from None
                        async with self.client.stream('GET', current) as response:
                            if response.is_redirect:
                                location = response.headers.get('location')
                                if not location:
                                    raise DiscoveryRequestError('redirect_missing_location')
                                if hop == 5:
                                    raise DiscoveryRequestError('redirect_limit')
                                current = urljoin(current, location)
                                _safe_url(current, host)
                                continue
                            status = response.status_code
                            if status != 200:
                                delay = retry_after(response.headers.get('retry-after'), self.clock())
                                if delay is not None and delay > 60:
                                    raise DiscoveryRequestError('retry_after_exceeds_limit', status_code=status)
                                raise DiscoveryRequestError(f'http_{status}', transient=status in (429, 500, 502, 503, 504),
                                                     retry_after=delay, status_code=status)
                            content_type = response.headers.get('content-type', '').split(';', 1)[0].lower().strip()
                            if content_type != 'application/json' and not content_type.endswith('+json'):
                                raise DiscoveryRequestError('unexpected_content_type')
                            body = await self._body(response)
                            headers = {key: value for key, value in response.headers.items() if key in
                                ('content-type', 'content-encoding', 'content-length', 'etag', 'last-modified', 'retry-after')}
                            return ResponseReceipt(body, current, status, headers, utc_now(), hop + 1)
            except (TimeoutError, httpx.TimeoutException):
                raise DiscoveryRequestError('request_timeout', transient=True) from None
            except httpx.TransportError:
                raise DiscoveryRequestError('transport_failure', transient=True) from None
            except zlib.error:
                raise DiscoveryRequestError('invalid_content_encoding') from None
        raise AssertionError('unreachable discovery redirect loop')
