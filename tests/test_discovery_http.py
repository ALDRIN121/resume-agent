import asyncio
import gzip
import json

import httpx
import pytest

URL='https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true'


class Chunks(httpx.AsyncByteStream):
    def __init__(self,chunks,delay=0):
        self.chunks,self.delay,self.closed=chunks,delay,False
    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk
    async def aclose(self):
        self.closed=True


@pytest.mark.asyncio
async def test_streaming_limit_includes_decoded_gzip_and_closes_response():
    from resume_agent.discovery.http import BoundedHttpClient,DiscoveryRequestError
    stream=Chunks([gzip.compress(b'a'*10000)])
    async def handler(request):
        return httpx.Response(200,headers={'content-type':'application/json','content-encoding':'gzip'},stream=stream)
    async with BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None,max_bytes=128) as client:
        with pytest.raises(DiscoveryRequestError) as failure:
            await client.fetch_once(URL)
    assert failure.value.code=='response_body_limit' and failure.value.partial
    assert stream.closed


@pytest.mark.asyncio
async def test_complete_utf8_json_preserves_decoded_body_and_duplicate_fields_are_rejected():
    from resume_agent.discovery.http import BoundedHttpClient,decode_json
    body=json.dumps({'jobs':[{'text':'C++ — C#'}]},ensure_ascii=False).encode()
    async def handler(request):
        return httpx.Response(200,headers={'content-type':'application/json','set-cookie':'session=do-not-retain'},stream=Chunks([body[:5],body[5:]]))
    async with BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None) as client:
        result=await client.fetch_once(URL)
    assert result.body==body and decode_json(result.body)['jobs'][0]['text']=='C++ — C#'
    assert 'set-cookie' not in result.headers
    with pytest.raises(ValueError):
        decode_json(b'{"jobs":[],"jobs":[1]}')


@pytest.mark.asyncio
async def test_redirect_outside_declared_provider_host_is_never_requested():
    from resume_agent.discovery.http import BoundedHttpClient,DiscoveryRequestError
    calls=[]
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'location':'https://example.invalid/private'},stream=Chunks([]))
    async with BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None) as client:
        with pytest.raises(DiscoveryRequestError) as failure:
            await client.fetch_once(URL)
    assert failure.value.code=='redirect_host_rejected' and calls==[URL]


@pytest.mark.asyncio
async def test_private_dns_is_rejected_before_transport(monkeypatch):
    from resume_agent.discovery.http import BoundedHttpClient,DiscoveryRequestError
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    calls=[]
    async def handler(request):
        calls.append(request)
        return httpx.Response(200,stream=Chunks([b'{}']))
    async with BoundedHttpClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscoveryRequestError) as failure:
            await client.fetch_once(URL)
    assert failure.value.code=='public_address_rejected' and calls==[]


@pytest.mark.asyncio
async def test_total_timeout_covers_streaming_and_three_request_slots_are_enforced():
    from resume_agent.discovery.http import BoundedHttpClient,DiscoveryRequestError
    async def slow(request):
        return httpx.Response(200,headers={'content-type':'application/json'},stream=Chunks([b'{}'],delay=.1))
    async with BoundedHttpClient(transport=httpx.MockTransport(slow),validator=lambda _:None,timeout=.01) as client:
        with pytest.raises(DiscoveryRequestError) as failure:
            await client.fetch_once(URL)
    assert failure.value.code=='request_timeout' and failure.value.transient
    active=peak=0
    async def handler(request):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.01)
        active-=1
        return httpx.Response(200,headers={'content-type':'application/json'},stream=Chunks([b'{}']))
    async with BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None) as client:
        await asyncio.gather(*(client.fetch_once(URL) for _ in range(12)))
    assert peak==3


@pytest.mark.asyncio
async def test_retry_after_over_sixty_seconds_stops_source():
    from resume_agent.discovery.http import BoundedHttpClient,DiscoveryRequestError
    async def handler(request):
        return httpx.Response(429,headers={'retry-after':'61'},stream=Chunks([]))
    async with BoundedHttpClient(transport=httpx.MockTransport(handler),validator=lambda _:None) as client:
        with pytest.raises(DiscoveryRequestError) as failure:
            await client.fetch_once(URL)
    assert failure.value.code=='retry_after_exceeds_limit' and not failure.value.transient
