"""Public A.V. identity/Firefox breadth-first regression (no user trace data)."""
import unittest
from unittest import mock

from open_law_lens import browser_recovery as b
from test_browser_recovery import (
    _FakeClient, _FakeLock, _FakeTime, _scoped_search,
    firefox_scholar_search_tree, node,
)

QUERY = '"In re A.V." C092928'
METADATA = '73 Cal. App. 5th 949 - Cal: Court of Appeal, 3rd Dist., 2021'


def results(metadata=METADATA):
    return firefox_scholar_search_tree(QUERY, [
        dict(title='In re AV', metadata=metadata, snippet='Unrelated excerpt.'),
        dict(title='IN RE AV', metadata='Cal: Court of Appeal, 2022',
             snippet='73 Cal.App.5th 949 C092928'),
    ])


class AVClient(_FakeClient):
    SEARCH_TITLE = 'Google Scholar'
    OPINION_TITLE = 'In re AV - Google Scholar'
    _search_tree = staticmethod(results)

    @staticmethod
    def _opinion_tree():
        # Breadth-first: the nested docket is returned AFTER all body nodes,
        # despite being in the document's front matter in reading order.
        return [
            node(0, 'application', 'Firefox'),
            node(1, 'frame', AVClient.OPINION_TITLE, parent=0),
            node(2, 'combo box', parent=1, text={
                'content': 'https://scholar.google.com/scholar_case?case=12345'}),
            node(3, 'document web', AVClient.OPINION_TITLE, parent=1,
                 states=['focused', 'showing', 'visible']),
            node(4, 'section', parent=3),
            node(5, 'section', '73 Cal.App.5th 949 (2021)', parent=4),
            node(6, 'section', parent=4),
            node(7, 'paragraph', 'OPINION ' + 'Synthetic body. ' * 80, parent=4),
            node(8, 'link', 'No. C092928.', parent=6),
        ]


class AVRegressionTests(unittest.TestCase):
    def matches(self, tree, query=QUERY, docket='C092928'):
        return b.find_result_matches(
            tree, _scoped_search(tree), '', 'In re A.V.',
            docket_number=docket, filing_year='2022',
            verified_search_query=query,
        )

    def run_job(self, client):
        request = b.ScholarRecoveryRequest(
            query=QUERY, expected_citation='', case_name='In re A.V.',
            docket_number='C092928', filing_year='2022',
        )
        with mock.patch.object(b, 'time', _FakeTime()), mock.patch.object(
            b, 'RecoveryLock', return_value=_FakeLock()
        ), mock.patch.object(b, 'launch_scholar_url',
                             return_value=('Firefox', 'firefox.desktop')):
            return b.ScholarRecoveryJob(request, client=client).run()

    def test_published_candidate_requires_docket_confirmation(self):
        matches = self.matches(results())
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].official_citation, '73 Cal.App.5th 949')
        self.assertTrue(matches[0].requires_docket_confirmation)

    def test_unverified_query_wrong_query_or_year_only_cannot_relax(self):
        for query in ('', 'In re A.V.', '"In re A.V." C999999'):
            with self.subTest(query=query):
                self.assertEqual(self.matches(results(), query=query), [])
        self.assertEqual(self.matches(results(), docket=''), [])

    def test_conflicting_metadata_docket_cannot_relax(self):
        self.assertEqual(self.matches(results(METADATA + ' No. C999999')), [])

    def test_two_published_candidates_remain_ambiguous(self):
        tree = firefox_scholar_search_tree(QUERY, [
            dict(title='In re AV', metadata=METADATA),
            dict(title='In re AV', metadata=METADATA.replace('949', '950')),
        ])
        self.assertEqual(len(self.matches(tree)), 2)
        client = AVClient()
        client._search_tree = lambda: tree
        outcome = self.run_job(client)
        self.assertEqual(outcome.reason_code, b.REASON_AMBIGUOUS_RESULTS)
        self.assertFalse(client.navigated)
        self.assertEqual(client.pressed, [])

    def test_full_job_opens_and_copies_original_opinion(self):
        client = AVClient()
        outcome = self.run_job(client)
        self.assertEqual(outcome.outcome, 'copied')
        self.assertTrue(client.navigated)
        self.assertEqual(client.pressed, [('Ctrl+A', 7), ('Ctrl+C', 7)])

    def test_missing_wrong_or_body_only_docket_prevents_copy(self):
        for kind in ('missing', 'wrong', 'body'):
            with self.subTest(kind=kind):
                tree = AVClient._opinion_tree()
                tree[-1]['name'] = 'No. C999999.' if kind == 'wrong' else ''
                # Even matching year cannot rescue this provisional candidate.
                tree[5]['name'] += ' 2022'
                if kind == 'body':
                    tree.append(node(9, 'paragraph', 'No. C092928.', parent=4))
                client = AVClient()
                client._opinion_tree = lambda: tree
                outcome = self.run_job(client)
                self.assertEqual(outcome.reason_code, b.REASON_IDENTITY_MISMATCH)
                self.assertEqual(client.pressed, [])

    def test_front_matter_uses_reading_order_and_stays_bounded(self):
        tree = AVClient._opinion_tree()[3:]
        text = b.front_matter_text(tree)
        self.assertIn('No. C092928.', text)
        self.assertLessEqual(len(text), 600)


if __name__ == '__main__':
    unittest.main()
