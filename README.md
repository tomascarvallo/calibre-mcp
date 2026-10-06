# Calibre MCP

An [MCP](https://modelcontextprotocol.io) server that automates [Calibre](https://calibre-ebook.com):
fetch and write ebook metadata, download covers, and convert books between formats — all from your AI assistant.

It wraps Calibre's own command-line tools (`ebook-meta`, `fetch-ebook-metadata`, `ebook-convert`, `calibredb`),
which are auto-detected on Windows, macOS and Linux.

## Requirements

- [Calibre](https://calibre-ebook.com/download) installed
- Python 3.10+

## Installation

```bash
git clone https://github.com/tomascarvallo/calibre-mcp.git
cd calibre-mcp
pip install -r requirements.txt
```

## Configuration

### Claude Desktop

Add this to `claude_desktop_config.json` (Settings → Developer → Edit Config) and restart Claude Desktop:

```json
{
  "mcpServers": {
    "calibre": {
      "command": "python",
      "args": ["/absolute/path/to/calibre-mcp/server.py"],
      "env": {
        "CALIBRE_LIBRARY": "/path/to/Calibre Library"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add calibre -- python /absolute/path/to/calibre-mcp/server.py
```

### Environment variables (both optional)

| Variable | Purpose |
|---|---|
| `CALIBRE_DIR` | Folder containing the Calibre executables, if auto-detection fails |
| `CALIBRE_LIBRARY` | Default library for the `library_*` tools |

## Tools

| Tool | Description |
|---|---|
| `calibre_info` | Calibre version and install path |
| `read_metadata` | Read an ebook's metadata |
| `set_metadata` | Write title, authors, series, tags, ISBN, cover, ... into the file |
| `extract_cover` | Extract the cover image |
| `fetch_metadata` | Search the internet for metadata (modifies nothing) |
| `auto_fill_metadata` | Download metadata + cover and write them into the book (only empty fields by default) |
| `batch_auto_fill_metadata` | Same, for a whole folder (`dry_run=true` by default) |
| `convert_book` | Convert to epub/mobi/azw3/pdf/docx/... (original is untouched; extra `ebook-convert` flags supported) |
| `batch_convert` | Convert a whole folder (`dry_run=true` by default) |
| `library_list` / `library_add` / `library_set_metadata` / `library_add_format` / `library_export` | Manage a Calibre library through `calibredb` |

## Example prompts

- "Fill in the missing metadata and covers for every EPUB in `~/Books/inbox`."
- "Convert all the MOBI files in this folder to EPUB and put them in `~/Books/epub`."
- "Convert this book to AZW3 for my Kindle."

## Notes

- Batch tools default to `dry_run=true`, so you see what would happen before anything is changed.
- No tool deletes books, by design.
- `calibredb` fails if the Calibre GUI has the library open; close Calibre first.
- Metadata is fetched using Calibre's configured sources (Google Books, Amazon, Open Library, ...).

## Development

```bash
python smoke_test.py   # converts a sample text file and exercises the metadata tools (needs internet)
```

## License

MIT
