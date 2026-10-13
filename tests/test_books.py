import sqlite3
from contextlib import closing
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
    with closing(sqlite3.connect(p)) as conn:
        conn.execute('CREATE TABLE example (value TEXT)')
        conn.execute("INSERT INTO example VALUES ('kept')")
        conn.commit()
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


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'BASE', tmp_path)
    folder = tmp_path / 'BKLibrary'
    folder.mkdir()
    path = tmp_path / 'a book.epub'
    path.write_text('placeholder')
    from contextlib import closing
    with closing(sqlite3.connect(folder / 'catalog.sqlite')) as conn:
        conn.execute('CREATE TABLE ZBKLIBRARYASSET (ZASSETID, ZTITLE, ZAUTHOR, ZPATH, ZREADINGPROGRESS, ZISFINISHED)')
        conn.executemany('INSERT INTO ZBKLIBRARYASSET VALUES (?,?,?,?,?,?)', [
            ('local', 'A Book', 'Author', path.as_uri(), .5, 0),
            ('cloud', 'Cloud Book', None, None, None, None),
        ])
        conn.commit()
    return path


def invoke(monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['apple-books', *args])
    return cli.main()


def test_catalog_search_and_resolution(library, monkeypatch):
    result = invoke(monkeypatch, 'list', '--query', 'AUTHOR', '--limit', '1')
    assert result['matches'] == 1
    assert result['books'][0]['file_present'] is True
    assert cli.resolve('local') == library
    assert cli.local_path(None) is None
    assert cli.local_path(str(library)) == library
    with pytest.raises(ValueError, match='not locally available'):
        cli.resolve('cloud')
    with pytest.raises(ValueError, match='exact asset ID'):
        cli.resolve('unknown')


def test_missing_database(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'BASE', tmp_path)
    with pytest.raises(ValueError, match='No BKLibrary database'):
        cli.catalog()


def test_notes_scoped_deleted_filtered_and_ordered(tmp_path, monkeypatch):
    from contextlib import closing
    monkeypatch.setattr(cli, 'BASE', tmp_path)
    folder = tmp_path / 'AEAnnotation'
    folder.mkdir()
    with closing(sqlite3.connect(folder / 'notes.sqlite')) as conn:
        conn.execute('CREATE TABLE ZAEANNOTATION (ZANNOTATIONSELECTEDTEXT, ZANNOTATIONNOTE, ZANNOTATIONLOCATION, ZANNOTATIONTYPE, ZANNOTATIONASSETID, ZANNOTATIONDELETED, ZANNOTATIONCREATIONDATE)')
        conn.executemany('INSERT INTO ZAEANNOTATION VALUES (?,?,?,?,?,?,?)', [
            ('second', 'note', 'loc2', 2, 'wanted', 0, 2),
            ('first', None, 'loc1', 2, 'wanted', 0, 1),
            ('deleted', None, '', 2, 'wanted', 1, 0),
            ('other book', None, '', 2, 'other', 0, 0),
        ])
        conn.commit()
    result = invoke(monkeypatch, 'notes', 'wanted', '--limit', '1')
    assert [x['text'] for x in result['annotations']] == ['first']


def test_pdf_single_page_and_full_search(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / 'test.pdf'
    path.touch()
    calls = []
    def extract(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout='target page\f' if '-f' in args else 'first\fsecond\f')
    monkeypatch.setattr(cli.subprocess, 'run', extract)
    result = invoke(monkeypatch, 'read', str(path), '--section', '7')
    assert result['section'] == 7 and result['text'] == 'target page'
    assert calls[0][2:6] == ['-f', '7', '-l', '7']
    assert cli.sections(path) == [('Page 1', 'first'), ('Page 2', 'second')]


def test_pdf_missing_tool(tmp_path, monkeypatch):
    def missing(*a, **kw):
        raise FileNotFoundError()
    monkeypatch.setattr(cli.subprocess, 'run', missing)
    with pytest.raises(ValueError, match='Poppler'):
        cli.sections(tmp_path / 'test.pdf')


def test_unsupported_and_corrupt_files(tmp_path):
    with pytest.raises(ValueError, match='EPUB and PDF'):
        cli.sections(tmp_path / 'book.mp3')
    path = tmp_path / 'broken.epub'
    path.write_text('not a zip')
    with pytest.raises(zipfile.BadZipFile):
        cli.sections(path)


def test_expanded_symlink_rejected(book, tmp_path):
    expanded = tmp_path / 'linked.epub'
    expanded.mkdir()
    (expanded / 'linked').symlink_to(book)
    with pytest.raises(ValueError, match='symlink'):
        cli.sections(expanded)


def test_toc_empty_search_and_limits(book, monkeypatch):
    assert len(invoke(monkeypatch, 'toc', str(book))['sections']) == 2
    assert invoke(monkeypatch, 'search', str(book), 'evidence', '--limit', '0')['hits'] == []
    assert invoke(monkeypatch, 'search', str(book), 'absent')['hits'] == []
    with pytest.raises(ValueError, match='empty'):
        invoke(monkeypatch, 'search', str(book), ' ')
    with pytest.raises(ValueError):
        invoke(monkeypatch, 'read', str(book), '--section', '99')


def test_json_output_and_error_exit(book, monkeypatch, capsys):
    import json
    monkeypatch.setattr(sys, 'argv', ['apple-books', 'toc', str(book)])
    cli.run()
    assert len(json.loads(capsys.readouterr().out)['sections']) == 2
    monkeypatch.setattr(sys, 'argv', ['apple-books', 'read', str(book), '--section', '0'])
    with pytest.raises(SystemExit) as exc:
        cli.run()
    assert exc.value.code == 1
    assert 'error' in json.loads(capsys.readouterr().err)


def test_chapter_heading_wins_over_wrong_navigation_title(tmp_path):
    b = epub.EpubBook()
    b.set_identifier('heading-check')
    b.set_title('Test')
    b.set_language('en')
    c = epub.EpubHtml(title='Wrong navigation title', file_name='chapter.xhtml')
    c.content = '<h1>Actual Chapter</h1><script>secret script</script><style>hidden css</style><p>Visible evidence.</p>'
    b.add_item(c)
    b.toc = ((epub.Section('Part'), [c]),)
    b.spine = [c]
    b.add_item(epub.EpubNav())
    p = tmp_path / 'heading.epub'
    epub.write_epub(p, b)
    result = cli.sections(p)
    assert result[0][0] == 'Actual Chapter'
    assert 'secret script' not in result[0][1]
    assert 'hidden css' not in result[0][1]
    assert 'Wrong navigation title' not in result[0][1]


def test_unicode_search_offsets_and_blank_page(book, monkeypatch):
    monkeypatch.setattr(cli, 'sections', lambda *a, **kw: [('Text', 'İ target'), ('Blank', '')])
    hit = invoke(monkeypatch, 'search', str(book), 'target')['hits'][0]
    assert hit['offset'] == 2  # Lowercasing İ expands it; offsets must stay in original text.
    result = invoke(monkeypatch, 'read', str(book), '--section', '2')
    assert result['text'] == '' and result['warning']


def test_pdf_extraction_failure_is_json_error(tmp_path, monkeypatch, capsys):
    import json
    import subprocess
    p = tmp_path / 'test.pdf'
    p.touch()
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['pdftotext'])
    monkeypatch.setattr(cli.subprocess, 'run', fail)
    monkeypatch.setattr(sys, 'argv', ['apple-books', 'read', str(p), '--section', '999'])
    with pytest.raises(SystemExit):
        cli.run()
    assert 'error' in json.loads(capsys.readouterr().err)
