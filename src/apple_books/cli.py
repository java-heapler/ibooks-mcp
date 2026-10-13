"""Read-only Apple Books catalog, annotations, and EPUB/PDF reader."""
import argparse
import json
import re
from contextlib import closing
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from ebooklib import epub

BASE = Path.home() / 'Library/Containers/com.apple.iBooksX/Data/Documents'


def db(sub):
    paths = sorted((BASE / sub).glob('*.sqlite'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        raise ValueError(f'No {sub} database found under {BASE}. Open Books and sync the library first.')
    conn = sqlite3.connect(paths[0].as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    conn.row_factory = sqlite3.Row
    return conn


def catalog():
    with closing(db('BKLibrary')) as conn:
        rows = conn.execute('SELECT ZASSETID id, ZTITLE title, ZAUTHOR author, ZPATH path, '
                            'ZREADINGPROGRESS progress, ZISFINISHED finished FROM ZBKLIBRARYASSET').fetchall()
    return [dict(r) for r in rows]


def local_path(raw):
    if not raw:
        return None
    return Path(unquote(urlparse(raw).path) if raw.startswith('file:') else raw).expanduser()


def resolve(value):
    p = Path(value).expanduser()
    if p.exists():
        return p
    matches = [r for r in catalog() if r['id'] == value]
    if not matches:
        raise ValueError('Use an exact asset ID from list, or an existing EPUB/PDF file path.')
    p = local_path(matches[0]['path'])
    if p is None or not p.exists():
        raise ValueError('Book content is not locally available. Download it in Apple Books, then retry.')
    return p


def sections(path, page=None):
    if path.suffix.lower() == '.pdf':
        try:
            page_args = ['-f', str(page), '-l', str(page)] if page is not None else []
            result = subprocess.run(['pdftotext', '-layout', *page_args, str(path), '-'], capture_output=True,
                                    text=True, check=True, timeout=120)
        except FileNotFoundError:
            raise ValueError('PDF reading requires pdftotext (Poppler).')
        pages = result.stdout.split('\f')
        if pages and not pages[-1].strip():
            pages.pop()
        return [(f'Page {i}', text.strip()) for i, text in enumerate(pages, page or 1)]
    if path.suffix.lower() != '.epub':
        raise ValueError('Text reading supports EPUB and PDF; audiobooks require a separate transcription workflow.')
    if path.is_dir():
        # Books stores imported EPUBs as expanded packages. Repackage only the
        # selected book temporarily so EbookLib can handle both storage forms.
        with tempfile.TemporaryDirectory(prefix='apple-books-') as temp:
            packed = Path(temp) / 'book.epub'
            with zipfile.ZipFile(packed, 'w', zipfile.ZIP_STORED) as archive:
                for entry in path.rglob('*'):
                    if entry.is_symlink():
                        raise ValueError('EPUB package contains a symlink; inspect it before reading.')
                    if entry.is_file():
                        archive.write(entry, entry.relative_to(path).as_posix())
            return sections(packed)
    with zipfile.ZipFile(path) as archive:
        if 'META-INF/encryption.xml' in archive.namelist():
            xml = BeautifulSoup(archive.read('META-INF/encryption.xml'), 'xml')
            methods = [x.get('Algorithm', '') for x in xml.find_all('EncryptionMethod')]
            # Font obfuscation does not encrypt chapter text.
            allowed = {'http://www.idpf.org/2008/embedding', 'http://ns.adobe.com/pdf/enc#RC'}
            if any(m not in allowed for m in methods):
                raise ValueError('EPUB contains protected resources; use readable content in Books. No DRM bypass is attempted.')
    book = epub.read_epub(str(path), options={'ignore_ncx': True})
    toc_titles = {}
    def collect_toc(entries):
        for entry in entries:
            if isinstance(entry, tuple):
                collect_toc([entry[0]])
                collect_toc(entry[1])
            elif getattr(entry, 'href', None):
                toc_titles.setdefault(unquote(entry.href.split('#')[0]), entry.title)
    collect_toc(book.toc)
    output = []
    for ident, _linear in book.spine:
        item = book.get_item_with_id(ident)
        if item is None:
            raise ValueError(f"EPUB spine references missing item: {ident}")
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        for tag in soup(['script', 'style']):
            tag.decompose()
        body = soup.body or soup
        heading = body.find(['h1', 'h2', 'h3'])
        title = (heading.get_text(' ', strip=True) if heading else None) or toc_titles.get(item.file_name) or item.file_name
        output.append((title, body.get_text(' ', strip=True)))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    ls = subs.add_parser('list')
    ls.add_argument('--query', default='')
    ls.add_argument('--limit', type=int, default=25)
    for name in ('toc', 'read', 'search', 'notes'):
        sub = subs.add_parser(name)
        sub.add_argument('book', help='Exact library asset ID, or file path (notes requires asset ID)')
        if name == 'read':
            sub.add_argument('--section', type=int, required=True, help='1-based EPUB spine section or PDF page')
            sub.add_argument('--offset', type=int, default=0)
            sub.add_argument('--chars', type=int, default=16000)
        if name == 'search':
            sub.add_argument('query')
            sub.add_argument('--limit', type=int, default=20)
        if name == 'notes':
            sub.add_argument('--limit', type=int, default=50)
    a = parser.parse_args()
    if a.command == 'list':
        rows = [r for r in catalog() if a.query.casefold() in
                f"{r['title'] or ''} {r['author'] or ''}".casefold()]
        for row in rows:
            p = local_path(row['path'])
            row['file_present'] = bool(p and p.exists())
        return {'matches': len(rows), 'books': rows[:max(0, a.limit)]}
    if a.command == 'notes':
        with closing(db('AEAnnotation')) as conn:
            rows = conn.execute('SELECT ZANNOTATIONSELECTEDTEXT text, ZANNOTATIONNOTE note, '
                                'ZANNOTATIONLOCATION location, ZANNOTATIONTYPE type '
                                'FROM ZAEANNOTATION WHERE ZANNOTATIONASSETID=? '
                                'AND COALESCE(ZANNOTATIONDELETED,0)=0 ORDER BY ZANNOTATIONCREATIONDATE '
                                'LIMIT ?', (a.book, max(0, a.limit))).fetchall()
        return {'annotations': [dict(r) for r in rows]}
    if a.command == 'read' and (a.section < 1 or a.offset < 0 or a.chars < 1):
        raise ValueError('Section and chars must be positive; offset must be nonnegative.')
    if a.command == 'search' and not a.query.strip():
        raise ValueError('Search query must not be empty.')
    path = resolve(a.book)
    single_page = a.command == 'read' and path.suffix.lower() == '.pdf'
    content = sections(path, page=a.section if single_page else None)
    if a.command == 'toc':
        return {'sections': [{'section': i, 'title': t, 'characters': len(s)}
                             for i, (t, s) in enumerate(content, 1)]}
    if a.command == 'read':
        index = 0 if single_page else a.section - 1
        if index >= len(content):
            raise ValueError('Section must exist, offset must be nonnegative, and chars must be positive.')
        title, text = content[index]
        end = min(len(text), a.offset + a.chars)
        return {'section': a.section, 'title': title, 'offset': a.offset, 'total_characters': len(text),
                'next_offset': end if end < len(text) else None, 'text': text[a.offset:end],
                'warning': None if text.strip() else 'No extractable text in this section; it may be blank or image-only. Inspect visually or use OCR.'}
    hits = []
    pattern = re.compile(re.escape(a.query), re.IGNORECASE)
    for i, (title, text) in enumerate(content, 1):
        if len(hits) >= max(0, a.limit):
            break
        for match in pattern.finditer(text):
            pos = match.start()
            hits.append({'section': i, 'title': title, 'offset': pos,
                         'excerpt': text[max(0, pos-180):match.end()+300]})
            if len(hits) >= a.limit:
                break
    return {'hits': hits, 'limit': a.limit}


def run():
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
