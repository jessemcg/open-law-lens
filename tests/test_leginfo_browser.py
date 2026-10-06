from __future__ import annotations

import io
import unittest
import tempfile
from pathlib import Path
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from open_law_lens import leginfo_browser as browser
from open_law_lens.statutes import LegInfoError, StatuteCitation, fetch_leginfo_statute, statute_url

CITATION = StatuteCitation('GOV', '815.6')
URL = statute_url('GOV', '815.6')
TEXT = 'GOVERNMENT CODE - GOV\n815.6.\nA public entity has a mandatory duty.\n(Added by Stats. 1963, Ch. 1681.)'
TITLE = 'California Code, GOV 815.6'


def node(index, role, parent=None, name='', text='', states=None):
    return dict(index=index, role=role, parent_index=parent, name=name,
                text={'content': text}, states=states or ['showing', 'visible'])


def page():
    return dict(window_context={'window_id': 7, 'title': TITLE + ' — Browser'},
                accessibility_tree=[
                    node(0, 'frame', name=TITLE + ' — Browser'),
                    node(1, 'combo box', 0, text=URL),
                    node(2, 'page tab', 0, name=TITLE, states=['selected','visible']),
                    node(3, 'document web', 0, name=TITLE, states=['showing','visible','focused']),
                    node(4, 'paragraph', 3, text=TEXT),
                ])


class ScopeTests(unittest.TestCase):
    def test_exact_identity(self):
        for url in [URL, URL.replace('https://', ''), URL + '.']:
            self.assertTrue(browser.section_url_matches(url, CITATION))
        for url in [URL.replace('https:', 'http:'), URL + '&lawCode=PEN',
                    URL + '&article=1', URL + '#history', URL.replace('GOV', 'WIC'),
                    URL.replace('815.6', '815.60'), URL.replace('.gov/', '.gov.evil/'),
                    URL.replace('codes_displaySection', 'codes_displayText'),
                    URL.replace('https://', 'https://user@')]:
            self.assertFalse(browser.section_url_matches(url, CITATION), url)

    def test_selected_document_only(self):
        p = page()
        p['accessibility_tree'] += [node(8,'document web',0,name='Other',states=['visible']),
                                    node(9,'paragraph',8,text='Verify you are human')]
        self.assertEqual([n['index'] for n in browser.selected_section(p,CITATION)], [3,4])

    def test_no_address_from_document_link(self):
        p=page();p['accessibility_tree'][1]['parent_index']=3
        self.assertEqual(browser.selected_section(p,CITATION), [])

    def test_wrong_address_or_frame_or_missing_document(self):
        for mutate in [lambda p:p['window_context'].update(title='Other'),
                       lambda p:p['accessibility_tree'][1].update(text={'content':URL+'0'}),
                       lambda p:p['accessibility_tree'][3].update(role='section')]:
            p=page();mutate(p)
            self.assertEqual(browser.selected_section(p,CITATION), [])

    def test_ambiguous_frame_and_address_rejected(self):
        for extra in [node(10,'frame',name=TITLE+' — Browser'), node(10,'entry',0,text=URL)]:
            p=page();p['accessibility_tree'].append(extra)
            self.assertEqual(browser.selected_section(p,CITATION), [])

    def test_valid_clipboard_excludes_chrome(self):
        result=browser.validated_clipboard_text('Navigation\n'+TEXT+'\nWebsite footer', CITATION)
        self.assertTrue(result.startswith('815.6.'))
        self.assertNotIn('Navigation',result)
        self.assertNotIn('Website footer',result)

    def test_bad_clipboard_rejected(self):
        for value in [TEXT.replace('GOVERNMENT CODE - GOV','PENAL CODE - PEN'),
                      TEXT.replace('GOVERNMENT CODE - GOV',''),
                      TEXT.replace('815.6.', '815.60.'),
                      TEXT.split('(Added')[0], 'Just a moment...',
                      TEXT.replace('A public entity has a mandatory duty.', 'Search'),
                      TEXT+'\n816.\nOther statutory provisions.\n(Added by Stats. 1970.)']:
            with self.assertRaises(LegInfoError):
                browser.validated_clipboard_text(value,CITATION)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.client=MagicMock(max_nodes=1000,max_depth=14)
        self.client.press_key.return_value={'ok':True}
        self.stack.enter_context(patch.object(browser,'ComputerUseMCPClient',return_value=self.client))
        self.lock=MagicMock();self.lock.acquire.return_value=True
        self.stack.enter_context(patch.object(browser,'RecoveryLock',return_value=self.lock))
        self.launch=self.stack.enter_context(patch.object(browser,'launch_default_https_url',return_value=('Browser','test.browser.desktop')))
        self.clipboard=self.stack.enter_context(patch.object(browser,'read_regular_clipboard',return_value=TEXT))
        self.stack.enter_context(patch.object(browser,'doctor_readiness',return_value=SimpleNamespace(
            blockers=[],can_register_mcp_tools=True,can_build_accessibility_tree=True,
            can_query_windows=True,can_send_development_input=True)))
        self.client.focused_window.return_value={'focused_window':{'window_id':1}}
        self.client.list_windows.return_value={'windows':[{'window_id':7,'title':TITLE,'app_id':'test.browser.desktop'}]}
        self.client.get_app_state.return_value=page()

    def test_one_default_launch_exact_keys_lock_cleanup(self):
        result=browser.recover_leginfo_text(CITATION)
        self.assertIn('mandatory duty',result)
        self.launch.assert_called_once_with(URL)
        self.assertEqual([c.kwargs for c in self.client.press_key.call_args_list],
                         [{'key':'Ctrl+A','window_id':7},{'key':'Ctrl+C','window_id':7}])
        self.lock.release.assert_called_once();self.client.close.assert_called_once()
        self.clipboard.assert_called_once_with(max_bytes=4*1024*1024)

    def test_busy_does_not_launch(self):
        self.lock.acquire.return_value=False
        with self.assertRaisesRegex(LegInfoError,'busy'):browser.recover_leginfo_text(CITATION)
        self.launch.assert_not_called()

    def test_timeout_does_not_launch(self):
        with self.assertRaisesRegex(LegInfoError,'timed out'):browser.recover_leginfo_text(CITATION,timeout=0)
        self.launch.assert_not_called();self.lock.release.assert_called_once()

    def test_wrong_copy_fails(self):
        self.clipboard.return_value=TEXT.replace('GOVERNMENT','PENAL')
        with self.assertRaisesRegex(LegInfoError,'identity'):browser.recover_leginfo_text(CITATION)
        self.lock.release.assert_called_once()

    def test_navigation_after_select_does_not_copy(self):
        wrong=page();wrong['accessibility_tree'][1]['text']['content']=URL+'0'
        self.client.get_app_state.side_effect=[page(),page(),wrong]
        with self.assertRaisesRegex(LegInfoError,'target'):browser.recover_leginfo_text(CITATION)
        self.assertEqual(self.client.press_key.call_count,1)
        self.clipboard.assert_not_called()

    def test_navigation_after_copy_does_not_read(self):
        wrong=page();wrong['accessibility_tree'][1]['text']['content']=URL+'0'
        self.client.get_app_state.side_effect=[page(),page(),page(),wrong]
        with self.assertRaisesRegex(LegInfoError,'changed'):browser.recover_leginfo_text(CITATION)
        self.clipboard.assert_not_called()

    def test_editable_document_control_does_not_copy(self):
        p=page();p['accessibility_tree'].append(node(5,'entry',3,states=['focused','visible']))
        self.client.get_app_state.return_value=p
        with self.assertRaisesRegex(LegInfoError,'focused'):browser.recover_leginfo_text(CITATION)
        self.client.press_key.assert_not_called()

    def test_challenge_left_untouched(self):
        p=page();p['accessibility_tree'][3]['name']='Verify you are human'
        p['accessibility_tree'] += [node(5,'heading',3,name='Verify you are human'),node(6,'check box',3)]
        self.client.get_app_state.return_value=p
        with self.assertRaisesRegex(LegInfoError,'verification'):browser.recover_leginfo_text(CITATION)
        self.client.press_key.assert_not_called();self.client.activate_window.assert_not_called()

    def test_failed_key_does_not_read_stale_clipboard(self):
        for keys in [[{'ok':False}], [{'ok':True}, {'ok':False}]]:
            self.client.press_key.side_effect=keys
            with self.assertRaisesRegex(LegInfoError,'failed'):
                browser.recover_leginfo_text(CITATION)
            self.clipboard.assert_not_called()

    def test_readiness_failure_does_not_launch(self):
        with patch.object(browser,'doctor_readiness',return_value=SimpleNamespace(blockers=['no display'])):
            with self.assertRaisesRegex(LegInfoError,'ready local'):
                browser.recover_leginfo_text(CITATION)
        self.launch.assert_not_called()

    def test_return_focus_only_if_browser_still_focused(self):
        self.client.focused_window.side_effect=[{'focused_window':{'window_id':1}},
                                               {'focused_window':{'window_id':7}}]
        browser.recover_leginfo_text(CITATION)
        self.assertEqual([c.kwargs for c in self.client.activate_window.call_args_list],
                         [{'window_id':7}, {'window_id':1}])

    def test_backend_error_cleanup(self):
        self.client.start.side_effect=browser.ComputerUseMCPError('Unavailable')
        with self.assertRaisesRegex(LegInfoError,'Unavailable'):browser.recover_leginfo_text(CITATION)
        self.launch.assert_not_called();self.lock.release.assert_called_once()


class FetchTests(unittest.TestCase):
    def test_403_recovers_once_with_truthful_provenance(self):
        error=HTTPError(URL,403,'Forbidden',{},io.BytesIO(b'challenge'))
        with patch('open_law_lens.statutes.urlopen',side_effect=error), patch.object(browser,'recover_leginfo_text',return_value='815.6. Official body') as recover:
            result=fetch_leginfo_statute(CITATION)
        recover.assert_called_once_with(CITATION)
        self.assertEqual(result['retrieval_mode'],'browser_clipboard')
        self.assertEqual(result['source_html'],'')
        self.assertEqual(result['source_url'],URL)

    def test_failed_recovery_cannot_write_authority_cache(self):
        from open_law_lens.cache import JsonCache
        from open_law_lens.client import CourtListenerClient
        from open_law_lens.library import CaseLibrary
        with tempfile.TemporaryDirectory() as root:
            cache=JsonCache(Path(root)/'cache')
            client=CourtListenerClient(cache=cache, library=CaseLibrary(Path(root)/'library.sqlite3'))
            with patch('open_law_lens.statutes.urlopen',side_effect=HTTPError(URL,403,'Forbidden',{},None)), patch.object(browser,'recover_leginfo_text',side_effect=LegInfoError('Rejected')), patch.object(cache,'upsert_statute') as upsert:
                with self.assertRaises(LegInfoError):client.lookup_statute('GOV 815.6')
                upsert.assert_not_called()

    def test_403_preserves_clear_failure(self):
        with patch('open_law_lens.statutes.urlopen',side_effect=HTTPError(URL,403,'Forbidden',{},None)), patch.object(browser,'recover_leginfo_text',side_effect=LegInfoError('Browser unavailable')):
            with self.assertRaisesRegex(LegInfoError,'HTTP 403.*Browser unavailable'):fetch_leginfo_statute(CITATION)

    def test_no_browser_for_network_or_other_http_errors(self):
        for error in [HTTPError(URL,404,'Missing',{},None),HTTPError(URL,429,'Throttled',{},None),URLError('offline'),TimeoutError()]:
            with patch('open_law_lens.statutes.urlopen',side_effect=error),patch.object(browser,'recover_leginfo_text') as recover:
                with self.assertRaises(LegInfoError):fetch_leginfo_statute(CITATION)
                recover.assert_not_called()

    def test_200_challenge_recovers(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'<title>Just a moment...</title>'
        with patch('open_law_lens.statutes.urlopen',return_value=response),patch.object(browser,'recover_leginfo_text',return_value='body') as recover:
            self.assertEqual(fetch_leginfo_statute(CITATION)['retrieval_mode'],'browser_clipboard')
            recover.assert_called_once()

    def test_direct_success_and_bad_body_never_launch(self):
        for body,valid in [(b'<div id="single_law_section">815.6. A mandatory duty exists.</div>',True),(b'<h1>Navigation only</h1>',False)]:
            response=MagicMock();response.__enter__.return_value.read.return_value=body
            with patch('open_law_lens.statutes.urlopen',return_value=response),patch.object(browser,'recover_leginfo_text') as recover:
                if valid:self.assertEqual(fetch_leginfo_statute(CITATION)['retrieval_mode'],'direct_http')
                else:
                    with self.assertRaises(LegInfoError):fetch_leginfo_statute(CITATION)
                recover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
