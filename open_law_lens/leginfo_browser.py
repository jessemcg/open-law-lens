"""Bounded, default-browser recovery of one current official LegInfo section.

No search, alternate source, model, browser profile, or durable library writes.
The Scholar lock also covers clipboard capture/validation, preventing concurrent
case/statute recoveries from operating on each other's tabs or clipboard.
"""
from __future__ import annotations

import html
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .browser_recovery import (
    RecoveryLock, _descendant_set, classify_page, document_copy_target_confirmed,
    node_name, node_role, node_text, scope_selected_document,
)
from .computer_use_mcp import ComputerUseMCPClient, ComputerUseMCPError, doctor_readiness
from .scholar_browser import (
    ScholarBrowserError, launch_default_https_url, read_regular_clipboard,
)
from .statutes import (
    CODE_LABELS, LegInfoError, StatuteCitation, extract_leginfo_text, statute_url,
)

BROWSER_TIMEOUT = 60.0


def section_url_matches(value: str, citation: StatuteCitation) -> bool:
    """Accept only the exact current section endpoint/identity, not archives."""
    try:
        # Browsers commonly omit the HTTPS scheme in the address-bar tree.
        if value.startswith('leginfo.legislature.ca.gov/'):
            value = 'https://' + value
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        return (
            parsed.scheme == 'https'
            and parsed.netloc.casefold() == 'leginfo.legislature.ca.gov'
            and parsed.path == '/faces/codes_displaySection.xhtml'
            and not parsed.fragment
            and set(query) == {'lawCode', 'sectionNum'}
            and query['lawCode'] == [citation.law_code]
            and query['sectionNum'] in ([citation.section], [citation.section + '.'])
        )
    except ValueError:
        return False


def _title_matches(title: str, citation: StatuteCitation) -> bool:
    return bool(re.fullmatch(
        rf'California Code,\s*{re.escape(citation.law_code)}\s+'
        rf'{re.escape(citation.section)}\.?', title.strip(), re.I,
    ))


def selected_section(payload: dict[str, Any], citation: StatuteCitation) -> list[dict]:
    """Require one exact compositor frame, its address bar and selected document.

    Never infer navigation from a hyperlink in page content or a background tab.
    Partial trees can establish front-matter identity, but supply no body text.
    """
    tree = payload.get('accessibility_tree') or []
    title = (payload.get('window_context') or {}).get('title', '')
    frames = [n for n in tree if node_role(n) == 'frame' and node_name(n) == title]
    if len(frames) != 1 or not title:
        return []
    indexes = _descendant_set(tree, int(frames[0]['index']))
    frame = [n for n in tree if n['index'] in indexes]
    documents = [n for n in frame if node_role(n) == 'document web']
    content_indexes = set()
    for document in documents:
        content_indexes.update(_descendant_set(tree, int(document['index'])))
    addresses = [node_text(n).strip() for n in frame
                 if n['index'] not in content_indexes
                 and node_role(n) in {'entry', 'text box', 'combo box'}
                 and section_url_matches(node_text(n).strip(), citation)]
    if len(addresses) != 1:
        return []
    selected = scope_selected_document(tree, frame)
    roots = [n for n in selected if node_role(n) == 'document web']
    if not roots or selected[0] is not roots[0]:
        return []
    return selected


def validated_clipboard_text(value: str, citation: StatuteCitation) -> str:
    """Require the code header, exact section and complete enactment end note."""
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    heading = re.search(rf'(?m)^\s*{re.escape(citation.section)}\.\s', value)
    if not heading:
        raise LegInfoError('LegInfo browser copy has no matching section heading.')
    front = value[:heading.start()]
    code_headers = re.findall(r'(?im)^\s*([A-Z][A-Z &.]* CODE)\s*-\s*([A-Z]+)\s*$', front)
    expected = (CODE_LABELS[citation.law_code].casefold(), citation.law_code)
    if not code_headers or any((label.casefold(), code.upper()) != expected
                               for label, code in code_headers):
        raise LegInfoError('LegInfo browser copy has missing or conflicting code identity.')
    # Browser selection must reach the official enactment note; a snippet or
    # partial selection is not a complete section. Fail closed if absent.
    body = value[heading.start():]
    if re.search(r'(?m)^\s*(?:Section\s+)?\d+[a-z]*(?:\.\d+[a-z]*)?\.\s', value[heading.end():], re.I):
        raise LegInfoError('LegInfo browser copy contains more than one section.')
    notes = list(re.finditer(
        r'(?m)^[ \t]*\((?:Amended|Added|Enacted|Repealed|Renumbered)\b[^\n]{0,4096}\)[ \t]*$',
        body, re.I,
    ))
    if not notes:
        raise LegInfoError('LegInfo browser copy is incomplete (no enactment end note).')
    substantive = body[:notes[-1].start()]
    if not re.search(r'[A-Za-z]{2,}\s+[A-Za-z]{2,}', substantive):
        raise LegInfoError('LegInfo browser copy has no substantive section body.')
    body = body[:notes[-1].end()]
    raw = '<div id="single_law_section">' + ''.join(
        '<p>' + html.escape(line) + '</p>' for line in body.splitlines()
    ) + '</div>'
    return extract_leginfo_text(raw, citation)


def recover_leginfo_text(citation: StatuteCitation, *, timeout: float = BROWSER_TIMEOUT) -> str:
    """One browser attempt; leave real challenges visible for the user."""
    lock = RecoveryLock()
    if not lock.acquire():
        raise LegInfoError('LegInfo browser recovery is busy: another authority recovery is running.')
    client = None
    origin = target = None
    blocked = False
    deadline = time.monotonic() + timeout

    def remaining() -> None:
        if time.monotonic() >= deadline:
            if blocked:
                raise LegInfoError('LegInfo browser verification did not finish. Complete it in the default browser, then retry.')
            raise LegInfoError('LegInfo browser recovery timed out; the section could not be verified.')

    def observe(window_id: int) -> list[dict]:
        remaining()
        payload = client.get_app_state(window_id=window_id,
                                       max_nodes=client.max_nodes, max_depth=client.max_depth)
        context = payload.get('window_context') or {}
        if context.get('window_id') != window_id:
            return []
        scoped = selected_section(payload, citation)
        nonlocal blocked
        if scoped:
            classification = classify_page(payload.get('accessibility_tree') or [], scoped, context='opinion')
            human_check = any(
                node_role(n) in {'heading', 'document web'}
                and 'showing' in (n.get('states') or [])
                and re.search(r'verify (?:that )?you are human', node_name(n), re.I)
                for n in scoped
            ) and any(node_role(n) in {'check box', 'checkbox', 'push button', 'button'}
                      and 'showing' in (n.get('states') or []) for n in scoped)
            if classification.classification == 'challenge' or human_check:
                blocked = True
                raise LegInfoError('LegInfo requires browser verification. Complete it in the default browser, then retry; the challenge was left untouched.')
            docs = [n for n in scoped if node_role(n) == 'document web']
            # A Cloudflare automatic check may settle without user action. Do
            # not touch it; only an exact statutory document can be copied.
            if docs and node_name(docs[0]).strip().casefold() in {'just a moment...', 'just a moment…'}:
                blocked = True
            if not docs or not _title_matches(node_name(docs[0]), citation):
                return []
            blocked = False
        return scoped

    try:
        client = ComputerUseMCPClient(job_deadline=timeout)
        client.start()
        readiness = doctor_readiness(client.doctor())
        if readiness.blockers or not all((readiness.can_register_mcp_tools,
                                         readiness.can_build_accessibility_tree,
                                         readiness.can_query_windows,
                                         readiness.can_send_development_input)):
            raise LegInfoError('LegInfo browser recovery requires a ready local Computer Use desktop.')
        origin = (client.focused_window().get('focused_window') or {}).get('window_id')
        remaining()
        handler_name, handler_id = launch_default_https_url(statute_url(citation.law_code, citation.section))
        handler_tokens = {re.sub(r'[^a-z0-9]', '', v.casefold().removesuffix('.desktop'))
                          for v in (handler_name, handler_id) if v}
        scoped = []
        while not scoped:
            remaining()
            windows = client.list_windows().get('windows') or []
            for window in windows:
                identity = {re.sub(r'[^a-z0-9]', '', str(window.get(k) or '').casefold().removesuffix('.desktop'))
                            for k in ('app_id', 'wm_class')}
                if not window.get('title') or not handler_tokens.intersection(identity):
                    continue
                window_id = window.get('window_id')
                if not isinstance(window_id, int) or window_id <= 0:
                    continue
                scoped = observe(window_id)
                if scoped:
                    target = window_id
                    break
            if not scoped:
                time.sleep(0.3)
        # Exact-ID validation before input, and selected-document URL checks
        # around copy prevent unrelated tabs from being imported. Gio may open
        # a background tab without granting focus; activate only the verified
        # numeric window, never an app-wide browser match.
        if not any(w.get('window_id') == target for w in client.list_windows().get('windows', [])):
            raise LegInfoError('LegInfo browser window disappeared before copying.')
        client.activate_window(window_id=target)
        scoped = observe(target)
        if not scoped:
            raise LegInfoError('LegInfo browser section changed before copying.')
        # Do not select/copy into an address bar or a page's search form.
        if not document_copy_target_confirmed(scoped):
            raise LegInfoError('LegInfo browser document is not focused; recovery stopped without copying.')
        if client.press_key(key='Ctrl+A', window_id=target).get('ok') is not True:
            raise LegInfoError('LegInfo browser selection failed; no text was imported.')
        scoped = observe(target)
        if not scoped or not document_copy_target_confirmed(scoped):
            raise LegInfoError('LegInfo browser copy target could not be verified.')
        if client.press_key(key='Ctrl+C', window_id=target).get('ok') is not True:
            raise LegInfoError('LegInfo browser copy failed; no text was imported.')
        if not observe(target):
            raise LegInfoError('LegInfo browser section changed during copying.')
        remaining()
        copied = read_regular_clipboard(max_bytes=4 * 1024 * 1024)
        if not observe(target):
            raise LegInfoError('LegInfo browser section changed while reading the copy.')
        return validated_clipboard_text(copied, citation)
    except (ComputerUseMCPError, ScholarBrowserError, OSError) as exc:
        raise LegInfoError('LegInfo default-browser recovery failed: ' + str(exc)) from exc
    finally:
        if client is not None:
            try:
                if not blocked and origin and target and origin != target:
                    focused = (client.focused_window().get('focused_window') or {}).get('window_id')
                    if focused == target:
                        client.activate_window(window_id=origin)
            except (ComputerUseMCPError, OSError):
                pass
            try:
                client.close()
            finally:
                lock.release()
        else:
            lock.release()
