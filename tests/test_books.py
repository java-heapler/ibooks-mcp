import sqlite3
import sys
import zipfile

import pytest
from ebooklib import epub
from apple_books import cli


@pytest.fixture
def book(tmp_path):
    b = epub.EpubBook()
    b.set_identifier('synthetic')
    b.set_title('Synthetic Book')
    b.set_language('en')
    chapters = []
    for i, word in enumerate(['Alpha', 'Beta']):
        c = epub.EpubHtml(title=word, file_name=f'{i}.xhtml', lang='en')
        c.content = f'<h1>{word}</h1><p>Evidence matters.</p>'
        b.add_item(c)
        chapters.append(c)
    b.toc = tuple(chapters)
    b.spine = chapters[::-1]
    b.add_item(epub.EpubNcx())
    b.add_item(epub.EpubNav())
    p = tmp_path / 'test.epub'
    epub.write_epub(p, b)
    return p


def test_spine_order_and_expanded_package(book, tmp_path):
    before = book.read_bytes()
    result = cli.sections(book)
    assert [title for title, text in result] == ['Beta', 'Alpha']
    assert 'Evidence matters.' in result[0][1]
    expanded = tmp_path / 'expanded.epub'
    with zipfile.ZipFile(book) as z:
        z.extractall(expanded)  # Only our own synthetic fixture.
    assert cli.sections(expanded) == result
    assert book.read_bytes() == before


def test_read_continuation_and_search(book, monkeypatch):
    def command(*args):
        monkeypatch.setattr(sys, 'argv', ['apple-books', *args])
        return cli.main()
    first = command('read', str(book), '--section', '1', '--chars', '5')
    rest = command('read', str(book), '--section', '1', '--offset', str(first['next_offset']))
    assert first['text'] + rest['text'] == cli.sections(book)[0][1]
    assert len(command('search', str(book), 'evidence', '--limit', '1')['hits']) == 1
    with pytest.raises(ValueError):
        command('read', str(book), '--section', '0')


def test_catalog_connection_is_read_only(tmp_path, monkeypatch):
    folder = tmp_path / 'BKLibrary'
    folder.mkdir()
    p = folder / 'test.sqlite'
    with sqlite3.connect(p) as conn:
        conn.execute('CREATE TABLE example (value TEXT)')
        conn.execute("INSERT INTO example VALUES ('kept')")
    monkeypatch.setattr(cli, 'BASE', tmp_path)
    conn = cli.db('BKLibrary')
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('DELETE FROM example')
        assert conn.execute('SELECT value FROM example').fetchone()[0] == 'kept'
    finally:
        conn.close()


def test_protected_epub_is_reported(book):
    with zipfile.ZipFile(book, 'a') as z:
        z.writestr('META-INF/encryption.xml', '<encryption><EncryptionMethod Algorithm="protected"/></encryption>')
    with pytest.raises(ValueError, match='protected'):
        cli.sections(book)
