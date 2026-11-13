"""Real font shaping must not split approved words during PDF extraction."""
import os
import shutil
from uuid import uuid4

import pytest

from resume_agent.approved_render import render_approved
from resume_agent.artifacts import RunArtifacts
from resume_agent.content_review import recompute_manifest
from resume_agent.pdf_content_check import verify_pdf_content
from resume_agent.schemas import DisplayField, RenderManifest

pytestmark = pytest.mark.skipif(
    os.getenv('RESUME_REQUIRE_PDF_TOOLS') != '1',
    reason='Real PDF tool acceptance flag not set',
)


@pytest.mark.parametrize('kind', ['heading', 'field', 'name'])
async def test_kerned_words_extract_as_the_exact_approved_tokens(tmp_path, kind):
    for tool in ('tectonic', 'pdftoppm', 'pdfinfo'):
        assert shutil.which(tool), f'Required PDF tool missing: {tool}'
    manifest = RenderManifest(
        source_revision='a' * 64,
        approved_proposal_ids=[],
        display_fields=[
            DisplayField(order=0, source_path='/skills/Tools/0',
                         text='Tools AVATAR To Wa Yo', kind=kind,
                         section='skills', group='tools'),
            DisplayField(order=1, source_path='/experience/0/bullets/0',
                         text='Helped reduce 450 ms to 90 ms; +80%, C++ and C#.',
                         kind='bullet', section='experience', group='0'),
        ],
        omissions=[], template_version='approved-v2', layout_id='standard',
        content_hash='0' * 64,
    )
    manifest = manifest.model_copy(update={'content_hash': recompute_manifest(manifest)})
    before = manifest.model_dump_json()
    artifacts = RunArtifacts.create(str(uuid4()), tmp_path / 'runs')
    rendered = await render_approved(manifest, artifacts, max_pages=2)
    checked = verify_pdf_content(manifest, rendered.pdf_path)
    assert checked.ok, checked
    assert checked.expected_hash == checked.actual_hash
    assert manifest.model_dump_json() == before
    assert not rendered.overflow
