from scripts.audit.inventory_bocc_archives import extract_metadata


def test_agricultural_nor_and_multiple_branches_are_preserved():
    row = extract_metadata(
        'BOCC 2026-03 AGR\nIDCC : 7001 | BÉTAIL\nIDCC : 7002 | CÉRÉALES\n'
        'Accord du 3 juin 2025\nrelatif à un observatoire\nNOR : AGRS2697011M\n'
        'IDCC : 9999\nTexte du corps'
    )
    assert row['nor'] == 'AGRS2697011M'
    assert row['idccs'] == ['7001', '7002']
    assert row['title'] == 'Accord du 3 juin 2025 relatif à un observatoire'


def test_interprofessional_document_without_idcc_is_not_discarded():
    row = extract_metadata(
        'Accord national interprofessionnel\nRETRAITE\n'
        'Avenant n° 29 du 15 octobre 2025\nNOR : ASET2650217M\nCorps'
    )
    assert row['idccs'] == []
    assert row['title'] == 'Avenant n° 29 du 15 octobre 2025'
    assert row['review_required'] is True


def test_unknown_header_stays_explicitly_unresolved():
    row = extract_metadata('Un document sans en-tête reconnu')
    assert row['nor'] is None and row['title'] is None
    assert row['review_required'] is True


def test_denunciation_is_preserved_as_a_document():
    row = extract_metadata(
        'Accord professionnel\nMÉDICO-SOCIAL\nDénonciation par lettre du 26 novembre 2025\n'
        'de la FNCLCC\nNOR : ASET2650555M\n'
    )
    assert row['title'].startswith('Dénonciation par lettre')


def test_inventory_preserves_unrecognized_pdf_and_counts_archive(tmp_path):
    import gzip
    import io
    import tarfile

    import pymupdf

    from scripts.audit.inventory_bocc_archives import inventory

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), 'Unknown header, retained for review')
        data = pdf.tobytes()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        member = tarfile.TarInfo('boc_20260001_0000_0001.pdf')
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    (tmp_path / '2026-01.taz').write_bytes(gzip.compress(buffer.getvalue()))
    result = inventory([{'numero': '2026-01', 'url': 'https://example.test/source'}],
                       tmp_path, tmp_path / 'output')
    assert len(result['documents']) == 1
    assert result['documents'][0]['nor'] is None
    assert result['documents'][0]['review_required'] is True
    assert result['archives'][0]['individual_pdfs'] == 1
    assert result['errors'] == []
