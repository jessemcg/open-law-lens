"""Lossless private source delivery; offsets are Python Unicode characters.

No authority verification, summarization, fingerprints or metrics are produced.
All filesystem mutations are relative to held, no-follow directory descriptors.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

MAX_PART_BYTES = 32 * 1024
MAX_PART_LINES = 1500
ARTIFACT_SCHEMA_VERSION = 1


def source_parts(text: str) -> Iterator[tuple[int, int, bytes]]:
    start = 0
    while start < len(text):
        # At most MAX_PART_BYTES characters can fit. Decode only complete UTF-8
        # codepoints; a cut codepoint is carried intact into the next slice.
        candidate = text[start:start + MAX_PART_BYTES].encode('utf-8')[:MAX_PART_BYTES]
        segment = candidate.decode('utf-8', errors='ignore')
        # Pi read splits on LF (including a trailing empty line). Bound that
        # representation, not just splitlines(), which drops the trailing LF.
        pos = -1
        for _ in range(MAX_PART_LINES):
            pos = segment.find('\n', pos + 1)
            if pos < 0:
                break
        if pos >= 0:
            segment = segment[:pos]
        end = start + len(segment)
        if end < len(text):
            paragraph = segment.rfind('\n\n')
            if paragraph >= 0:
                end = start + paragraph + 2
        data = text[start:end].encode('utf-8')
        yield start, end, data
        start = end


def validate_destination(destination: str | Path, workspace: str | Path | None = None) -> Path:
    path = Path(destination)
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        raise ValueError('Artifact destination must be an absolute new directory without parent traversal.')
    if workspace is not None:
        root = Path(workspace)
        if not root.is_absolute() or '..' in root.parts or path == root or not path.is_relative_to(root):
            raise ValueError('Artifact destination must be inside the declared private agent workspace.')
    return path


def _open_parent(path: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def export_source_artifacts(
    payload: dict[str, Any], destination: str | Path, *, workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Exclusive export. On error remove only files created by this invocation.

    Parents must exist and may not be symlinks. The source payload stays unchanged.
    Failure is raised for the CLI to report nonzero structured JSON.
    """
    path = validate_destination(destination, workspace)
    text = payload.get('text')
    if not isinstance(text, str):
        raise ValueError('Extraction did not supply source text.')
    if payload.get('ok') is False:
        raise ValueError('Failed extraction cannot be exported as a successful source.')
    parent = _open_parent(path)
    directory = None
    created = False
    written: list[str] = []
    inode = None
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
        created = True
        inode = os.stat(path.name, dir_fd=parent, follow_symlinks=False).st_ino
        directory = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=parent)
        if os.fstat(directory).st_ino != inode:
            raise OSError('Artifact directory changed during creation.')
        os.fchmod(directory, 0o700)

        def write(name: str, data: bytes) -> None:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
            written.append(name)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, 'wb', closefd=False) as handle:
                    handle.write(data)
            finally:
                os.close(fd)

        parts = []
        for number, (start, end, data) in enumerate(source_parts(text), 1):
            name = f'part-{number:04d}.txt'
            write(name, data)
            parts.append({'name': name, 'start_offset': start, 'end_offset': end,
                          'byte_count': len(data), 'line_count': data.count(b'\n') + 1})
        metadata = {key: value for key, value in payload.items() if key != 'text'}
        metadata['text_length'] = len(text)
        manifest = {'schema_version': ARTIFACT_SCHEMA_VERSION,
                    'offset_convention': 'Unicode characters, zero-based, end-exclusive',
                    'chunk_numbers_are_pinpoints': False, 'text_length': len(text),
                    'byte_count': len(text.encode('utf-8')), 'parts': parts}
        for name, obj in (('metadata.json', metadata), ('manifest.json', manifest)):
            write(name, (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        if os.stat(path.name, dir_fd=parent, follow_symlinks=False).st_ino != inode:
            raise OSError('Artifact destination changed before publication.')
        return {'ok': True, 'export_status': 'complete', 'output_dir': str(path),
                'metadata_path': str(path / 'metadata.json'), 'manifest_path': str(path / 'manifest.json'),
                'part_count': len(parts), 'text_length': len(text), 'byte_count': manifest['byte_count']}
    except BaseException:
        if directory is not None:
            for name in reversed(written):
                os.unlink(name, dir_fd=directory)
        if created:
            # Never remove a replacement destination or anything we didn't create.
            try:
                current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if current is not None and inode is not None and current.st_ino == inode:
                os.rmdir(path.name, dir_fd=parent)
        raise
    finally:
        if directory is not None:
            os.close(directory)
        os.close(parent)
