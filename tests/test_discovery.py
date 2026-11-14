"""Fictional public-board fixtures; discovery never needs credentials or models."""
from urllib.parse import parse_qs,urlsplit
from uuid import uuid4

import pytest


def source(provider='greenhouse',**extra):
    from resume_agent.discovery.schemas import DiscoverySource
    return DiscoverySource(id=str(uuid4()),provider=provider,board='example',company='Example',**extra)


def greenhouse(job_id=1,**extra):
    return {'id':job_id,'title':'Python Engineer','location':{'name':'Berlin'},
            'absolute_url':f'https://boards.greenhouse.io/example/jobs/{job_id}',
            'content':'<p>Work with C++ &amp; C#.</p>',**extra}


def lever(job_id='one',**extra):
    return {'id':job_id,'text':'Engineer','hostedUrl':f'https://jobs.lever.co/example/{job_id}',
        'descriptionPlain':'Opening and body together.','lists':[{'text':'Requirements','content':'<li>Python</li>'}],
        'additionalPlain':'Closing text.','salaryDescriptionPlain':'€90,000–€100,000',
        'categories':{'location':'Berlin','commitment':'Full-time'},**extra}


def ashby(job_id='one',**extra):
    return {'title':'Engineer','location':'Berlin','descriptionPlain':'Complete job description.',
            'jobUrl':f'https://jobs.ashbyhq.com/example/{job_id}','isListed':True,'workplaceType':'Remote',**extra}


@pytest.mark.asyncio
async def test_greenhouse_complete_text_and_explicit_count():
    from resume_agent.discovery.providers import fetch_board
    urls=[]
    async def fetch(url):
        urls.append(url)
        return {'jobs':[greenhouse()], 'meta':{'total':1}}
    result=await fetch_board(source(),fetch)
    assert result.status=='complete' and result.valid_count==1
    assert 'content=true' in urls[0]
    assert 'Work with C++ & C#.' in result.jobs[0].text
    assert result.jobs[0].raw['content']=='<p>Work with C++ &amp; C#.</p>'


@pytest.mark.asyncio
async def test_lever_pagination_preserves_sections_without_duplicating_combined_opening():
    from resume_agent.discovery.providers import fetch_board
    skips=[]
    async def fetch(url):
        skip=int(parse_qs(urlsplit(url).query)['skip'][0]);skips.append(skip)
        return [lever(str(i)) for i in range(100)] if skip==0 else [lever('last')]
    result=await fetch_board(source('lever'),fetch)
    assert result.status=='complete' and result.valid_count==101 and skips==[0,100]
    text=result.jobs[0].text
    assert text.count('Opening and body together.')==1
    assert all(value in text for value in ['Requirements','Python','Closing text.','€90,000–€100,000'])


@pytest.mark.asyncio
async def test_ashby_uses_documented_url_identity_and_honors_unlisted():
    from resume_agent.discovery.providers import fetch_board
    async def fetch(url):
        return {'apiVersion':'1','jobs':[ashby(),ashby('hidden',isListed=False)]}
    result=await fetch_board(source('ashby'),fetch)
    assert result.status=='complete' and result.valid_count==1 and result.filtered_count==1
    assert result.jobs[0].external_id=='https://jobs.ashbyhq.com/example/one'
    assert 'Remote' in result.jobs[0].text


@pytest.mark.asyncio
async def test_malformed_duplicate_and_conflicting_ids_are_conservative_partial():
    from resume_agent.discovery.providers import fetch_board
    async def fetch(url):
        return {'jobs':[greenhouse(1),greenhouse(1),greenhouse(2),greenhouse(2,title='Conflicting title'),
                        {'title':'Missing ID'},greenhouse(3)],'meta':{'total':6}}
    result=await fetch_board(source(),fetch)
    assert result.status=='partial' and result.duplicate_count==2 and result.conflicting_count==1
    assert result.malformed_count==1
    assert {job.external_id for job in result.jobs}=={'1','3'}


@pytest.mark.asyncio
async def test_missing_ashby_identity_and_oversized_posting_are_not_silently_repaired():
    from resume_agent.discovery.providers import fetch_board
    async def fetch(url):
        bad=ashby();bad.pop('jobUrl')
        return {'apiVersion':'1','jobs':[bad,ashby('huge',descriptionPlain='a'*48001),ashby('valid')]}
    result=await fetch_board(source('ashby'),fetch)
    assert result.status=='partial' and result.malformed_count==2 and result.valid_count==1


@pytest.mark.asyncio
async def test_limit_and_page_failure_cannot_claim_complete():
    from resume_agent.discovery.providers import fetch_board
    from resume_agent.discovery.schemas import DiscoveryError
    async def overflow(url):
        return {'jobs':[greenhouse(i) for i in range(1,4)],'meta':{'total':3}}
    capped=await fetch_board(source(),overflow,max_jobs=2)
    assert capped.status=='partial' and capped.truncated_count==1 and capped.valid_count==2
    async def failure(url):
        if 'skip=0' in url:
            return [lever(str(i)) for i in range(100)]
        raise DiscoveryError('http_503')
    partial=await fetch_board(source('lever'),failure)
    assert partial.status=='partial' and partial.valid_count==100


@pytest.mark.asyncio
async def test_empty_is_complete_and_total_mismatch_is_partial():
    from resume_agent.discovery.providers import fetch_board
    async def empty(url):
        return {'jobs':[],'meta':{'total':0}}
    assert (await fetch_board(source(),empty)).status=='complete'
    async def missing(url):
        return {'jobs':[],'meta':{'total':2}}
    assert (await fetch_board(source(),missing)).status=='partial'


def test_sources_reject_arbitrary_urls_paths_credentials_and_nonlever_regions():
    from resume_agent.discovery.providers import board_url
    from resume_agent.discovery.schemas import DiscoverySource
    assert urlsplit(board_url(source('lever',region='eu'))).hostname=='api.eu.lever.co'
    for body in [{'board':'../private'},{'board':'https://127.0.0.1'},{'url':'http://localhost'},
                 {'api_key':'secret'},{'provider':'greenhouse','region':'eu'}]:
        with pytest.raises(ValueError):
            DiscoverySource.model_validate({'id':str(uuid4()),'provider':'greenhouse','board':'example',**body})


@pytest.mark.asyncio
async def test_malformed_duplicate_cannot_replace_prior_unambiguous_posting():
    from resume_agent.discovery.providers import fetch_board
    async def fetch(url):
        return {'jobs':[greenhouse(1),greenhouse(1,content=None),greenhouse(2,content='<p></p>')], 'meta':{'total':3}}
    result=await fetch_board(source(),fetch)
    assert result.status=='partial' and result.duplicate_count==1 and result.malformed_count==2
    assert result.valid_count==0 and result.conflicting_count==1


@pytest.mark.asyncio
async def test_malformed_total_metadata_prevents_clean_completeness():
    from resume_agent.discovery.providers import fetch_board
    async def fetch(url):
        return {'jobs':[greenhouse()], 'meta':[]}
    assert (await fetch_board(source(),fetch)).status=='partial'


@pytest.mark.asyncio
async def test_default_thousand_record_bound_is_inclusive_for_unpaginated_boards():
    from resume_agent.discovery.providers import fetch_board
    async def exact(url):
        return {'jobs':[greenhouse(i) for i in range(1,1001)],'meta':{'total':1000}}
    result=await fetch_board(source(),exact)
    assert result.status=='complete' and result.valid_count==1000 and not result.limit_reached
