"""MCP server for Calibre: read/write/fetch metadata and convert ebooks.

Wraps Calibre's command-line tools (ebook-meta, fetch-ebook-metadata,
ebook-convert, calibredb). Optional environment variables:

  CALIBRE_DIR      Folder with the Calibre executables (auto-detected on Windows/macOS/Linux).
  CALIBRE_LIBRARY  Default library path for the library_* tools.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calibre")

EBOOK_EXTS = {
    ".epub", ".mobi", ".azw", ".azw3", ".kfx", ".pdf", ".fb2", ".docx", ".rtf",
    ".txt", ".htmlz", ".lit", ".lrf", ".odt", ".cbz", ".cbr", ".djvu", ".pdb", ".snb",
}
CONVERT_TIMEOUT = 1800
META_TIMEOUT = 120


# --------------------------------------------------------------------------- helpers
def _calibre_dir() -> Path:
    env = os.environ.get("CALIBRE_DIR")
    candidates = [Path(env)] if env else []
    candidates += [
        Path(r"C:\Program Files\Calibre2"),
        Path(r"C:\Program Files (x86)\Calibre2"),
        Path("/Applications/calibre.app/Contents/MacOS"),
        Path("/opt/calibre"),
        Path("/usr/bin"),
    ]
    for c in candidates:
        if any((c / n).exists() for n in ("ebook-convert.exe", "ebook-convert")):
            return c
    found = shutil.which("ebook-convert")
    if found:
        return Path(found).parent
    raise RuntimeError("Calibre not found. Set the CALIBRE_DIR environment variable.")


def _exe(name: str) -> str:
    d = _calibre_dir()
    for n in (f"{name}.exe", name):
        if (d / n).exists():
            return str(d / n)
    raise RuntimeError(f"{name} not found in {d}")


def _run(cmd: list[str], timeout: int = META_TIMEOUT) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env,
    )


def _fail(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or proc.stdout or "unknown error").strip()[-2000:]


def _file(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ValueError(f"File not found: {p}")
    return p


def _parse_opf(opf: Path) -> dict:
    ns = {
        "opf": "http://www.idpf.org/2007/opf",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    root = ET.parse(opf).getroot()
    md = root.find("opf:metadata", ns)
    if md is None:
        return {}

    def texts(tag: str) -> list[str]:
        return [e.text.strip() for e in md.findall(f"dc:{tag}", ns) if e.text and e.text.strip()]

    out: dict = {
        "title": (texts("title") or [None])[0],
        "authors": texts("creator"),
        "publisher": (texts("publisher") or [None])[0],
        "date": (texts("date") or [None])[0],
        "language": (texts("language") or [None])[0],
        "tags": texts("subject"),
        "comments": (texts("description") or [None])[0],
        "identifiers": {},
    }
    for e in md.findall("dc:identifier", ns):
        scheme = e.get("{http://www.idpf.org/2007/opf}scheme")
        if scheme and e.text:
            out["identifiers"][scheme.lower()] = e.text.strip()
    for m in md.findall("opf:meta", ns):
        name, content = m.get("name"), m.get("content")
        if name == "calibre:series":
            out["series"] = content
        elif name == "calibre:series_index":
            out["series_index"] = content
        elif name == "calibre:rating":
            out["rating"] = content
        elif name == "calibre:title_sort":
            out["title_sort"] = content
    return {k: v for k, v in out.items() if v not in (None, [], {}, "")}


def _read_meta(path: Path) -> dict:
    with tempfile.TemporaryDirectory() as td:
        opf = Path(td) / "meta.opf"
        proc = _run([_exe("ebook-meta"), str(path), "--to-opf", str(opf)])
        if proc.returncode != 0 or not opf.exists():
            raise RuntimeError(_fail(proc))
        return _parse_opf(opf)


def _meta_args(
    title=None, authors=None, author_sort=None, title_sort=None, publisher=None,
    series=None, series_index=None, tags=None, comments=None, isbn=None,
    language=None, pubdate=None, rating=None, identifiers=None, cover=None,
) -> list[str]:
    a: list[str] = []

    def add(flag: str, val):
        if val is not None and val != "":
            a.extend([flag, str(val)])

    add("--title", title)
    add("--authors", " & ".join(authors) if authors else None)
    add("--author-sort", author_sort)
    add("--title-sort", title_sort)
    add("--publisher", publisher)
    add("--series", series)
    add("--index", series_index)
    add("--tags", ",".join(tags) if tags else None)
    add("--comments", comments)
    add("--isbn", isbn)
    add("--language", language)
    add("--date", pubdate)
    add("--rating", rating)
    for k, v in (identifiers or {}).items():
        a.extend(["--identifier", f"{k}:{v}"])
    if cover:
        a.extend(["--cover", str(_file(cover))])
    return a


def _iter_books(directory: Path, recursive: bool, exts: set[str]):
    it = directory.rglob("*") if recursive else directory.glob("*")
    for p in sorted(it):
        if p.is_file() and p.suffix.lower() in exts:
            yield p


# --------------------------------------------------------------------------- general
@mcp.tool()
def calibre_info() -> dict:
    """Show the detected Calibre version and the folder with its executables."""
    proc = _run([_exe("ebook-convert"), "--version"])
    return {
        "calibre_dir": str(_calibre_dir()),
        "version": proc.stdout.strip().splitlines()[0] if proc.stdout else None,
        "default_library": os.environ.get("CALIBRE_LIBRARY"),
    }


# --------------------------------------------------------------------------- metadata
@mcp.tool()
def read_metadata(path: str) -> dict:
    """Read an ebook's metadata (title, authors, series, tags, ISBN, etc.)."""
    return _read_meta(_file(path))


@mcp.tool()
def set_metadata(
    path: str,
    title: str | None = None,
    authors: list[str] | None = None,
    author_sort: str | None = None,
    title_sort: str | None = None,
    publisher: str | None = None,
    series: str | None = None,
    series_index: float | None = None,
    tags: list[str] | None = None,
    comments: str | None = None,
    isbn: str | None = None,
    language: str | None = None,
    pubdate: str | None = None,
    rating: int | None = None,
    identifiers: dict[str, str] | None = None,
    cover_path: str | None = None,
) -> dict:
    """Write metadata INTO the ebook file (modifies the file).

    Only the fields you pass are changed. `pubdate` as YYYY-MM-DD, `rating` 1-5,
    `identifiers` e.g. {"isbn": "...", "goodreads": "..."}.
    """
    p = _file(path)
    args = _meta_args(title, authors, author_sort, title_sort, publisher, series,
                      series_index, tags, comments, isbn, language, pubdate, rating,
                      identifiers, cover_path)
    if not args:
        raise ValueError("No fields given to modify.")
    proc = _run([_exe("ebook-meta"), str(p), *args])
    if proc.returncode != 0:
        raise RuntimeError(_fail(proc))
    return {"updated": str(p), "metadata": _read_meta(p)}


@mcp.tool()
def extract_cover(path: str, output_path: str | None = None) -> dict:
    """Extract an ebook's cover to an image file (default: next to the book, .jpg)."""
    p = _file(path)
    out = Path(output_path).expanduser().resolve() if output_path else p.with_suffix(".cover.jpg")
    proc = _run([_exe("ebook-meta"), str(p), "--get-cover", str(out)])
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(_fail(proc) or "The book has no cover.")
    return {"cover": str(out)}


def _fetch(title, authors, isbn, identifiers, cover_out, timeout) -> tuple[dict, str]:
    cmd = [_exe("fetch-ebook-metadata"), "--opf", "--timeout", str(timeout)]
    if title:
        cmd += ["--title", title]
    if authors:
        cmd += ["--authors", " & ".join(authors)]
    if isbn:
        cmd += ["--isbn", isbn]
    for k, v in (identifiers or {}).items():
        cmd += ["--identifier", f"{k}:{v}"]
    if cover_out:
        cmd += ["--cover", cover_out]
    if not (title or authors or isbn):
        raise ValueError("Provide at least a title, author or ISBN.")
    proc = _run(cmd, timeout=timeout + 30)
    if proc.returncode != 0 or "<package" not in proc.stdout:
        raise RuntimeError("No metadata found. " + _fail(proc))
    opf_text = proc.stdout[proc.stdout.index("<?xml") if "<?xml" in proc.stdout else proc.stdout.index("<package"):]
    with tempfile.NamedTemporaryFile("w", suffix=".opf", delete=False, encoding="utf-8") as f:
        f.write(opf_text)
        tmp = f.name
    try:
        return _parse_opf(Path(tmp)), opf_text
    finally:
        os.unlink(tmp)


@mcp.tool()
def fetch_metadata(
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
    identifiers: dict[str, str] | None = None,
    timeout: int = 45,
) -> dict:
    """Search the internet for metadata (Google Books, Amazon, OpenLibrary...) WITHOUT modifying any file."""
    meta, _ = _fetch(title, authors, isbn, identifiers, None, timeout)
    return meta


@mcp.tool()
def auto_fill_metadata(
    path: str,
    download_cover: bool = True,
    overwrite_existing: bool = False,
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
    timeout: int = 45,
) -> dict:
    """Download metadata and cover from the internet and write them into the ebook.

    Uses the book's own ISBN/title/author unless given explicitly.
    With overwrite_existing=False only empty fields of the book are filled in.
    """
    p = _file(path)
    current = _read_meta(p)
    q_title = title or current.get("title")
    q_authors = authors or [a for a in current.get("authors", []) if a.lower() not in ("unknown", "desconocido")]
    q_isbn = isbn or current.get("identifiers", {}).get("isbn")
    q_ids = {k: v for k, v in current.get("identifiers", {}).items() if k != "isbn"}

    td = tempfile.mkdtemp(prefix="calibre_mcp_")
    try:
        cover_file = str(Path(td) / "cover.jpg") if download_cover else None
        fetched, _ = _fetch(q_title, q_authors, q_isbn, q_ids, cover_file, timeout)

        def want(field: str) -> bool:
            return overwrite_existing or not current.get(field)

        fields = {}
        for key in ("title", "publisher", "series", "comments", "language"):
            if fetched.get(key) and want(key):
                fields[key] = fetched[key]
        if fetched.get("authors") and (overwrite_existing or not q_authors):
            fields["authors"] = fetched["authors"]
        if fetched.get("series_index") and "series" in fields:
            fields["series_index"] = fetched["series_index"]
        if fetched.get("tags") and want("tags"):
            fields["tags"] = fetched["tags"]
        if fetched.get("date") and want("date"):
            fields["pubdate"] = fetched["date"][:10]
        ids = {k: v for k, v in fetched.get("identifiers", {}).items()
               if overwrite_existing or k not in current.get("identifiers", {})}
        if ids:
            fields["identifiers"] = ids
        cover_set = False
        if cover_file and Path(cover_file).exists():
            fields["cover_path"] = cover_file
            cover_set = True

        if not fields:
            return {"updated": False, "reason": "Nothing to fill in.", "metadata": current}
        args = _meta_args(
            fields.get("title"), fields.get("authors"), None, None, fields.get("publisher"),
            fields.get("series"), fields.get("series_index"), fields.get("tags"),
            fields.get("comments"), None, fields.get("language"), fields.get("pubdate"),
            None, fields.get("identifiers"), fields.get("cover_path"),
        )
        proc = _run([_exe("ebook-meta"), str(p), *args])
        if proc.returncode != 0:
            raise RuntimeError(_fail(proc))
        return {
            "updated": True,
            "fields_written": sorted(k for k in fields if k != "cover_path"),
            "cover_updated": cover_set,
            "metadata": _read_meta(p),
        }
    finally:
        shutil.rmtree(td, ignore_errors=True)


@mcp.tool()
def batch_auto_fill_metadata(
    directory: str,
    recursive: bool = False,
    download_cover: bool = True,
    overwrite_existing: bool = False,
    dry_run: bool = True,
) -> dict:
    """Run auto_fill_metadata on every ebook in a folder.

    For safety `dry_run=True` by default: it only lists which books would be processed.
    """
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        raise ValueError(f"Folder not found: {d}")
    books = list(_iter_books(d, recursive, EBOOK_EXTS))
    if dry_run:
        return {"dry_run": True, "count": len(books), "files": [str(b) for b in books]}
    results = []
    for b in books:
        try:
            r = auto_fill_metadata(str(b), download_cover, overwrite_existing)
            results.append({"file": str(b), "updated": r["updated"],
                            "fields": r.get("fields_written", [])})
        except Exception as e:  # noqa: BLE001 - keep going with the rest of the batch
            results.append({"file": str(b), "error": str(e)[:300]})
    return {"dry_run": False, "count": len(books),
            "ok": sum(1 for r in results if "error" not in r), "results": results}


# --------------------------------------------------------------------------- conversion
@mcp.tool()
def convert_book(
    input_path: str,
    output_format: str = "epub",
    output_path: str | None = None,
    overwrite: bool = False,
    extra_options: list[str] | None = None,
    copy_metadata: bool = True,
) -> dict:
    """Convert an ebook to another format with ebook-convert (epub, mobi, azw3, pdf, docx, txt, fb2...).

    The original is never modified. By default the output is written next to the original
    with the new extension. `extra_options` accepts ebook-convert flags, e.g.
    ["--output-profile", "kindle"], ["--margin-left", "10"], ["--enable-heuristics"].
    For Kindle, azw3 or epub is recommended.
    """
    src = _file(input_path)
    fmt = output_format.lower().lstrip(".")
    out = Path(output_path).expanduser().resolve() if output_path else src.with_suffix(f".{fmt}")
    if out == src:
        raise ValueError("Output file is the same as the input file.")
    if out.exists() and not overwrite:
        raise ValueError(f"{out} already exists. Use overwrite=true to replace it.")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([_exe("ebook-convert"), str(src), str(out), *(extra_options or [])],
                timeout=CONVERT_TIMEOUT)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(_fail(proc))
    return {"input": str(src), "output": str(out), "size_bytes": out.stat().st_size}


@mcp.tool()
def batch_convert(
    directory: str,
    output_format: str = "epub",
    output_directory: str | None = None,
    recursive: bool = False,
    skip_existing: bool = True,
    extra_options: list[str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Batch-convert every ebook in a folder to the given format.

    `dry_run=True` by default: only shows what would be converted. Books already in the
    target format are skipped.
    """
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        raise ValueError(f"Folder not found: {d}")
    fmt = output_format.lower().lstrip(".")
    out_dir = Path(output_directory).expanduser().resolve() if output_directory else None
    jobs = []
    for b in _iter_books(d, recursive, EBOOK_EXTS):
        if b.suffix.lower() == f".{fmt}":
            continue
        target = (out_dir or b.parent) / f"{b.stem}.{fmt}"
        if skip_existing and target.exists():
            continue
        jobs.append((b, target))
    if dry_run:
        return {"dry_run": True, "count": len(jobs),
                "jobs": [{"input": str(a), "output": str(b)} for a, b in jobs]}
    results = []
    for src, target in jobs:
        try:
            results.append(convert_book(str(src), fmt, str(target), True, extra_options))
        except Exception as e:  # noqa: BLE001
            results.append({"input": str(src), "error": str(e)[:300]})
    return {"dry_run": False, "count": len(jobs),
            "ok": sum(1 for r in results if "error" not in r), "results": results}


# --------------------------------------------------------------------------- library (calibredb)
def _lib(library: str | None) -> str:
    lib = library or os.environ.get("CALIBRE_LIBRARY")
    if not lib:
        raise ValueError("Pass `library` or set the CALIBRE_LIBRARY environment variable.")
    return str(Path(lib).expanduser().resolve())


@mcp.tool()
def library_list(
    library: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List books in a Calibre library. `search` uses Calibre's search syntax
    (e.g. 'author:Borges', 'tags:fiction', 'formats:epub'). Close the Calibre GUI if the library is locked."""
    cmd = [_exe("calibredb"), "list", "--library-path", _lib(library), "--for-machine",
           "--fields", "id,title,authors,series,tags,formats,identifiers",
           "--limit", str(limit)]
    if search:
        cmd += ["--search", search]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(_fail(proc))
    import json
    return json.loads(proc.stdout or "[]")


@mcp.tool()
def library_add(paths: list[str], library: str | None = None, duplicates: bool = False) -> dict:
    """Add ebook files to the Calibre library."""
    files = [str(_file(p)) for p in paths]
    cmd = [_exe("calibredb"), "add", "--library-path", _lib(library), *files]
    if duplicates:
        cmd.insert(2, "--duplicates")
    proc = _run(cmd, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(_fail(proc))
    return {"output": proc.stdout.strip()}


@mcp.tool()
def library_set_metadata(
    book_id: int,
    fields: dict[str, str],
    library: str | None = None,
) -> dict:
    """Modify fields of a library book. `fields` e.g. {"title": "...",
    "authors": "A & B", "tags": "x,y", "series": "...", "series_index": "2", "publisher": "..."}."""
    if not fields:
        raise ValueError("fields is empty.")
    cmd = [_exe("calibredb"), "set_metadata", "--library-path", _lib(library), str(book_id)]
    for k, v in fields.items():
        cmd += ["--field", f"{k}:{v}"]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(_fail(proc))
    return {"output": proc.stdout.strip() or "ok"}


@mcp.tool()
def library_add_format(book_id: int, file_path: str, library: str | None = None) -> dict:
    """Add a file (e.g. a converted epub) as an extra format of an existing book."""
    cmd = [_exe("calibredb"), "add_format", "--library-path", _lib(library),
           str(book_id), str(_file(file_path))]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(_fail(proc))
    return {"output": proc.stdout.strip() or "ok"}


@mcp.tool()
def library_export(
    book_ids: list[int],
    destination: str,
    library: str | None = None,
) -> dict:
    """Export library books to a folder (with metadata and cover)."""
    dest = Path(destination).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [_exe("calibredb"), "export", "--library-path", _lib(library),
           "--to-dir", str(dest), *map(str, book_ids)]
    proc = _run(cmd, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(_fail(proc))
    return {"destination": str(dest), "output": proc.stdout.strip()}


if __name__ == "__main__":
    mcp.run()
