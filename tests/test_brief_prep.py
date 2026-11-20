from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens import brief_prep as prep
from open_law_lens.agent_prompts import brief_prep_request
from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary


def pdf(path: Path, *sheets: list[str]) -> Path:
    """Small valid synthetic PDF, no external test dependencies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    page_ids = []
    for lines in sheets:
        page, content = len(objects) + 1, len(objects) + 2
        page_ids.append(f'{page} 0 R')
        stream = b'BT /F1 12 Tf 30 700 Td 22 TL ' + b' T* '.join(
            b'(' + line.encode('ascii').replace(b'(', b'\\(').replace(b')', b'\\)') + b') Tj' for line in lines
        ) + b' ET\n'
        objects.extend([f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>'.encode(),
                       f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'endstream'])
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(page_ids)}] /Count {len(page_ids)} >>'.encode()
    data, offsets = b'%PDF-1.4\n', [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{off:010} 00000 n \n'.encode() for off in offsets[1:])
    data += f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(data)
    return path


TITLE = {"AOB": "Appellant's Opening Brief", "RB": "Respondent's Brief", "MTD": "Respondent's Motion to Dismiss Appeal"}


@unittest.skipUnless(shutil.which('pdftotext') and shutil.which('pdfimages'), 'Poppler required')
class SourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "B123456 Synthetic's Case"
        self.root.mkdir()
        self.case = prep.validate_case_root(self.root)
        self.work = Path(temp.name) / 'workspace'
        self.work.mkdir()

    def filing(self, name, role, number='B123456', text='Synthetic first argument.'):
        return pdf(self.root / name, ["California Court of Appeal", f"No. {number}", TITLE[role]], [text])

    def test_three_variants_lossless_sources_and_unchanged_tree(self):
        aob = self.filing('1_briefs/Filed originals/AOB.pdf', 'AOB')
        shutil.copyfile(aob, self.filing('1_briefs/Filed originals/AOB-copy.pdf', 'AOB'))
        self.filing('1_briefs/drafts/AOB.pdf', 'AOB', text='draft only')
        self.filing('archive/AOB.pdf', 'AOB', text='archived duplicate')
        self.filing('1_briefs/RB.pdf', 'RB')
        self.filing('1_briefs/Other RB.pdf', 'RB', 'C111111')
        self.filing('motions/Final document.pdf', 'MTD')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for kind, roles in [('reply', ['aob', 'rb']), ('respondent', ['aob']), ('opposition', ['mtd', 'aob'])]:
            with self.subTest(kind=kind):
                work = self.work / kind
                work.mkdir()
                found = prep.discover(self.case, kind, work)
                self.assertEqual(found.provenance, prep.PrepProvenance(kind, 'B123456'))
                self.assertEqual(list(found.choices), roles)
                self.assertTrue(all(len(options) == 1 for options in found.choices.values()))
                chosen = {role: options[0] for role, options in found.choices.items()}
                manifest = prep.stage_evidence(self.case, found, chosen, work)
                for item in json.loads(manifest.read_text())['filings']:
                    index = work / item['parts']
                    parts = json.loads(index.read_text())['parts']
                    body = b''.join((index.parent / part['name']).read_bytes() for part in parts).decode()
                    self.assertEqual(body, chosen[item['role']].text)
                    self.assertEqual(body.count('\f'), 2)
                self.assertIn(f'variant: {kind}', brief_prep_request(kind, manifest))
                self.assertNotIn(str(self.root), manifest.read_text())
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_missing_wrong_case_role_and_opposition_without_context(self):
        self.filing('AOB.pdf', 'AOB', 'D234567')
        self.filing('MTD.pdf', 'MTD')
        pdf(self.root / 'RB.pdf', ['B123456', "Appellant's Reply to Respondent's Brief"])
        with self.assertRaisesRegex(prep.PrepError, r'(?s)opening brief.*different appeal'):
            prep.discover(self.case, 'reply', self.work)
        found = prep.discover(self.case, 'opposition', self.work)
        self.assertEqual(list(found.choices), ['mtd'])
        self.assertIn('Optional', found.optional_warning)
        self.filing('Filed AOB.pdf', 'AOB')
        with self.assertRaisesRegex(prep.PrepError, 'respondent’s brief'):
            prep.discover(self.case, 'reply', self.work)

    def test_same_rank_nonduplicates_require_a_choice_and_records_are_confined(self):
        self.filing('subfolder/AOB-1.pdf', 'AOB')
        self.filing('subfolder/AOB-2.pdf', 'AOB', text='Different filing on the same appeal.')
        bundle = self.root / '0_record/case_bundle'
        pages = bundle / 'text_pages'
        pages.mkdir(parents=True)
        (bundle / 'artifacts').mkdir()
        (bundle / 'manifest.json').write_text(json.dumps({'files': {'toc': '../../toc.txt'}}))
        (self.root / 'toc.txt').write_text('OUTSIDE')
        (bundle / 'config.json').write_text('DO NOT COPY')
        (bundle / 'artifacts/toc.txt').symlink_to(self.root / 'toc.txt')
        for page in range(1, 7):
            (pages / f'{page:04d}.txt').write_text(f'Existing synthetic page {page}.')
        (pages / '0007.txt').symlink_to(self.root / 'toc.txt')
        rows = [('RT 3', 'selected'), ('RT 4', 'ambiguous'), ('CT 6', 'selected'), ('CT 6', 'selected'),
                ('CT 7', 'missing'), ('CT 8', 'selected'), ('RT 12', 'selected')]
        (bundle / 'artifacts/transcript_page_numbers.json').write_text(json.dumps({'schema_version': 2, 'entries': [
            {'file_name': f'{i:04d}.txt', 'citation_label': label, 'status': status, 'confidence': 'low' if i == 6 else 'high'}
            for i, (label, status) in enumerate(rows, 1)]}))
        found = prep.discover(self.case, 'respondent', self.work)
        self.assertEqual([f.path.as_posix() for f in found.choices['aob']], ['subfolder/AOB-1.pdf', 'subfolder/AOB-2.pdf'])
        manifest = prep.stage_evidence(self.case, found, {'aob': found.choices['aob'][1]}, self.work)
        record = json.loads(manifest.read_text())['record']
        self.assertEqual(record['page_count'], 6)
        self.assertEqual(record['unmapped_or_ambiguous_pages'], 6)
        self.assertEqual(record['omitted_text_pages'], 1)
        self.assertNotIn('toc', record['sources'])
        self.assertEqual((self.work / 'record/selected_page_map/part-0001.txt').read_text(), 'RT 3\ttext_pages/0001.txt\n')
        self.assertFalse(list(self.work.rglob('config.json')))

    def test_scan_requires_searchable_copy_without_local_ocr(self):
        source = pdf(self.root / 'AOB.pdf', [])
        def ocr(staged):
            self.assertNotEqual(staged, source)
            self.assertEqual(staged.read_bytes(), source.read_bytes())
            raise prep.PrepError('Provide a searchable PDF copy.')
        with patch.object(prep, '_scanned_sheets', return_value={0}), patch.object(prep, '_local_ocr', side_effect=ocr):
            with self.assertRaisesRegex(prep.PrepError, 'searchable PDF copy'):
                prep.discover(self.case, 'respondent', self.work, allow_ocr=True)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertFalse(source.with_suffix('.txt').exists())

    def test_mixed_ocr_keeps_searchable_sheets_verbatim_and_requires_every_scan(self):
        source = self.filing('AOB.pdf', 'AOB')
        with patch.object(prep, '_local_ocr', return_value='lower-quality OCR\fRecovered scan text\f'):
            self.assertEqual(prep._fill_scanned_sheets(source, 'Native searchable text\f 1\f', {1}),
                             'Native searchable text\fRecovered scan text\f')
        with patch.object(prep, '_local_ocr', return_value='only one sheet\f'):
            with self.assertRaisesRegex(prep.PrepError, 'searchable PDF copy'):
                prep._fill_scanned_sheets(source, 'Native text\f\f', {1})

    def test_unattributed_motion_title_does_not_prove_respondent_filed(self):
        pdf(self.root / 'MTD.pdf', ['B123456', 'Motion to Dismiss Appeal', 'Synthetic, Respondent'])
        with self.assertRaisesRegex(prep.PrepError, 'respondent’s motion'):
            prep.discover(self.case, 'opposition', self.work)
        pdf(self.root / 'MTD.pdf', ['B123456', 'Motion to Dismiss Appeal', 'Attorney for Respondent'])
        self.assertEqual(list(prep.discover(self.case, 'opposition', self.work).choices), ['mtd'])

    def test_root_pin_fails_on_replacement_and_symlinks(self):
        alias = self.root.with_name('link')
        alias.symlink_to(self.root, target_is_directory=True)
        for path in (alias, Path('relative'), self.root / '..'):
            with self.assertRaises(prep.PrepError):
                prep.validate_case_root(path)
        self.root.rename(self.root.with_name('original'))
        self.root.mkdir()
        with self.assertRaisesRegex(prep.PrepError, 'folder changed'):
            prep.discover(self.case, 'reply', self.work)


class SavedPrepTests(unittest.TestCase):
    def test_namespaced_ids_and_research_set_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = JsonCache(root / 'cache')
            library = CaseLibrary(root / 'library.sqlite3')
            library.ensure()
            text = '# Argument About Notice\n*Check the waiver*\n\nSynthetic.'
            plain = cache.save_agent_answer(text)
            self.assertEqual(plain, hashlib.sha256(text.encode()).hexdigest()[:24])
            self.assertNotIn('brief_prep', cache.read_agent_answer(plain))
            profs = [prep.PrepProvenance('reply', 'B123456'), prep.PrepProvenance('respondent', 'B123456'),
                     prep.PrepProvenance('reply', 'A765432')]
            ids = [cache.save_agent_answer(text, prep=profile) for profile in profs]
            self.assertEqual(len(set([plain, *ids])), 4)
            cache.set_agent_answer_selected(ids[0], True)
            library.save_research_set('Synthetic', cache)
            cache.clear()
            self.assertEqual(cache.list_agent_answer_entries(), [])
            library.load_research_set_into_cache('Synthetic', cache)
            self.assertTrue(cache.is_agent_answer_selected(ids[0]))
            self.assertEqual({e['answer_id'] for e in cache.list_agent_answer_entries()}, {plain, *ids})
            for answer_id, profile in zip(ids, profs):
                self.assertEqual(cache.read_agent_answer(answer_id)['brief_prep'], profile.payload())
                self.assertEqual(cache.read_agent_answer_index()[answer_id]['brief_prep'], profile.payload())
