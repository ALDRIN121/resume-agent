"""Real PDF extraction: complete ordered display equality, never factual verification."""
from __future__ import annotations

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from resume_agent.content_review import recompute_manifest
from resume_agent.schemas import DisplayField, RenderManifest


def make_manifest(text='Cut 450ms to 90ms (+80%-gain).', *, label=None):
    value = RenderManifest(source_revision='a' * 64, approved_proposal_ids=[],
        display_fields=[DisplayField(order=0, source_path='/summary', text=text,
            kind='field', section='summary', group='summary', visible_label=label)],
        omissions=[], template_version='approved-v2', layout_id='standard', content_hash='0' * 64)
    return value.model_copy(update={'content_hash': recompute_manifest(value)})


def make_pdf(path, text, *, pages=1):
    """Small valid Type0 PDF with an explicit Unicode map; extraction uses pypdf."""
    writer = PdfWriter()
    chars = sorted(set(text))
    cmap = '\n'.join(f'<{ord(c):04x}> <{ord(c):04x}>' for c in chars)
    mapping = DecodedStreamObject()
    mapping.set_data(('begincmap\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\n'
        'endcodespacerange\n' + str(len(chars)) + ' beginbfchar\n' + cmap +
        '\nendbfchar\nendcmap').encode())
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type0'), NameObject('/BaseFont'): NameObject('/Test'),
        NameObject('/Encoding'): NameObject('/Identity-H'),
        NameObject('/DescendantFonts'): ArrayObject(),
        NameObject('/ToUnicode'): writer._add_object(mapping)})
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 10 Tf 40 740 Td <' + text.encode('utf-16-be').hex() + '> Tj ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as target:
        writer.write(target)
    return path


def test_accepts_exact_full_text_and_labels(tmp_path):
    from resume_agent.pdf_content_check import verify_pdf_content
    result = verify_pdf_content(make_manifest(label='Summary:'),
        make_pdf(tmp_path / 'exact.pdf', 'Summary: Cut 450ms to 90ms (+80%-gain).'))
    assert result.ok and result.page_count == 1
    assert result.expected_hash == result.actual_hash
    assert result.mismatch_index is None


@pytest.mark.parametrize('actual', [
    'Cut 450ms to (+80%-gain).', 'Cut Cut 450ms to 90ms (+80%-gain).',
    'cut 450ms to 90ms (+80%-gain).', 'Cut 450ms to 90ms (+80%gain).',
    'Cut 450ms to 90ms (-80%-gain).', 'Cut 450s to 90ms (+80%-gain).',
    'Cut 90ms to 450ms (+80%-gain).', '90ms Cut 450ms to (+80%-gain).',
    'Cut 450ms to 90ms (+80%-gain). EXTRA',
])
def test_rejects_missing_repeated_changed_reordered_and_extra_tokens(tmp_path, actual):
    from resume_agent.pdf_content_check import verify_pdf_content
    result = verify_pdf_content(make_manifest(), make_pdf(tmp_path / 'changed.pdf', actual))
    assert not result.ok and result.code == 'content_mismatch'
    assert result.expected_hash != result.actual_hash
    assert isinstance(result.mismatch_index, int)
    assert actual not in repr(result)  # diagnostics do not disclose resume text


def test_only_ligatures_and_whitespace_are_normalized(tmp_path):
    from resume_agent.pdf_content_check import verify_pdf_content
    assert verify_pdf_content(make_manifest('office first flow'),
        make_pdf(tmp_path / 'ligature.pdf', 'oﬃce\tﬁrst  ﬂow')).ok
    for approved, actual in [('2²', '22'), ('①', '1'), ('㎏', 'kg'), ('A-B', 'AB')]:
        assert not verify_pdf_content(make_manifest(approved),
            make_pdf(tmp_path / 'symbol.pdf', actual)).ok


@pytest.mark.parametrize('case', ['malformed', 'empty', 'encrypted', 'blank', 'missing'])
def test_blocks_unreadable_empty_encrypted_or_missing_pages(tmp_path, case):
    from resume_agent.pdf_content_check import verify_pdf_content
    path = tmp_path / 'bad.pdf'
    if case == 'malformed':
        path.write_bytes(b'not a PDF')
    elif case != 'missing':
        writer = PdfWriter()
        if case in {'encrypted', 'blank'}:
            writer.add_blank_page(width=612, height=792)
        if case == 'encrypted':
            writer.encrypt('secret')
        with path.open('wb') as target:
            writer.write(target)
    assert not verify_pdf_content(make_manifest(), path).ok


def test_invalid_manifest_hash_returns_sanitized_failure(tmp_path):
    from resume_agent.pdf_content_check import verify_pdf_content
    manifest = make_manifest().model_copy(update={'content_hash': 'f' * 64})
    result = verify_pdf_content(manifest, make_pdf(tmp_path / 'invalid-manifest.pdf', 'secret data'))
    assert not result.ok and result.code == 'invalid_manifest'
    assert 'secret data' not in repr(result)
