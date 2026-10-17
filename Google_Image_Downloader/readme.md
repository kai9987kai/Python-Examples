# ImageForge 2.0 — Image Search, Downloader & Local Gallery

ImageForge is a modern, standalone replacement for a legacy Google Images / WallpapersCraft downloader. It uses Python 3.10+ on Windows, macOS, and Linux, avoids OS-specific drive changes, and manages downloaded images in an organised local library.

## Install

```bash
python -m pip install -r requirements.txt
```

On Windows, `py -m pip install -r requirements.txt` and `py imageforge.py` also work.

## Start the original-style menu

```bash
python imageforge.py
```

The original menu slots are preserved:

1. General image search & download (now using the maintained multi-engine `ddgs` library rather than the obsolete Google `rg_meta` markup)
2. WallpapersCraft Full HD / 1920 × 1080 download
3. Show downloaded images and actual pixel dimensions
4. Set image directory, cross-platform
5. Exit

Additional menu items:

6. Wikimedia Commons image search, with creator and licence metadata
7. Generate an offline, searchable, responsive HTML gallery
8. Validate saved files and report exact duplicates
9. Google Images using Custom Search JSON API for *existing* Google API customers

## Command line examples

```bash
# General web image search (no search-engine API key required)
python imageforge.py search "fantasy landscape" --source web --limit 15

# Wikimedia Commons metadata-aware image search
python imageforge.py search "Hubble nebula" --source commons --limit 20

# WallpapersCraft resolution-verified 1920×1080 images (third-party site)
python imageforge.py search "galaxy" --source wallpaperscraft --limit 10

# Filter out low-resolution images; use a chosen directory
python imageforge.py --output "D:/Art/Reference" search "architecture" --source web --limit 20 --min-width 1600 --min-height 900

# Produce local HTML preview at Images/gallery.html
python imageforge.py gallery

# Scan all local images, without deleting anything
python imageforge.py verify

# List image dimensions
python imageforge.py list

# More diagnostics
python imageforge.py --verbose search "forest" --source commons --limit 5
```

Note that the `--output` flag comes **before** the subcommand. The default directory is `Images` below the current terminal working directory.

## Optional Google integration (legacy customers only)

The Google Custom Search JSON API was **closed to new customers** and is scheduled to end on **1 January 2027**. The original legacy Google Images scraping method using `div.rg_meta` no longer provides a reliable source. If you already have the API and a search-engine ID, set these environment variables and run:

PowerShell:

```powershell
$env:GOOGLE_CSE_API_KEY = Read-Host "Existing Google API key"
$env:GOOGLE_CSE_ID = Read-Host "Programmable Search Engine ID"
py imageforge.py search "landscape" --source google --limit 10
```

Linux/macOS:

```bash
read -r -s -p 'Existing Google API key: ' GOOGLE_CSE_API_KEY; echo
read -r -p 'Programmable Search Engine ID: ' GOOGLE_CSE_ID
export GOOGLE_CSE_API_KEY GOOGLE_CSE_ID
python imageforge.py search 'landscape' --source google --limit 10
```

Do not commit API keys to public repositories. This Google mode is transitional; the default `web` and `commons` modes do not need Google credentials.

## Storage

```text
Images/
├── commons/
│   └── hubble-nebula/
│       └── example-title-<12-char-sha256>.jpg
├── web/
│   └── architecture/
├── wallpaperscraft/
│   └── galaxy/
├── google/
│   └── landscape/
├── gallery.html
└── manifest.jsonl
```

The filename contains a digest, not a sequential counter. The manifest records image title, original image URL, source page URL, format, dimensions, creator/credit if provided, licence if provided, content SHA-256, filesize, and UTC download timestamp.

## Improvements over the original

| Capability | Original | ImageForge 2.0 |
| --- | --- | --- |
| Image search | Brittle Google `rg_meta` HTML parsing | Maintained `ddgs` multi-engine results; optional legacy Google JSON API |
| Wallpaper downloads | Fragile URL string slicing | Follow current wallpaper listing and download-page links, verify exact 1920×1080 |
| Save folder | Global `chdir`, Windows-only `X:\` paths | `pathlib` paths, on all major platforms |
| Network resilience | No explicit timeout / retries | Timeouts, retries, HTTP status checks, throttled sequential requests |
| Content validation | Saves any HTTP body as `.jpg` | Pillow format validation; real extension; pixel dimensions; download size cap |
| Duplicate handling | Overwrites sequential filenames | Content-addressed names, SHA-256 deduplication across folders |
| Provenance | None | Structured JSONL manifest and Wikimedia licence metadata |
| Gallery | List folder names only | Searchable offline HTML gallery plus detailed image listing |
| Modes | Interactive only | Interactive menu plus CLI for scripting |
| Secrets | N/A | Existing Google API key from environment variables, never embedded in code |
| Testing | No tests | Offline regression suite |

## Limitations and responsible use

- WallpapersCraft is a third-party website, not an official API. Its HTML, access policies, and download restrictions can change. HTTP 403/429, blocked requests, changed tags, or changed page structure may stop this source. ImageForge does not evade CAPTCHAs or access controls.
- Exact 1920×1080 dimensions are verified after download; they are **not** fabricated by upscaling lower-resolution images.
- Wikimedia Commons hosts multiple licences. Licensing metadata is recorded to aid verification, not to guarantee unrestricted usage. WallpapersCraft and general web search results may be copyrighted even when freely viewable or downloadable. Check author credit and licence on the source page, especially before redistributing, commercial use, or use in games.
- Not all multi-engine results contain image bytes at their linked URL; those failures are skipped. Internet access and availability are required for real downloads.
- Downloads use a 25 MiB limit by default, with `--max-mb` to adjust. Images larger than 80 million pixels are rejected. No image file is deleted by the built-in verification mode.
- Input URL checks block direct private-IP and localhost URLs, but this desktop downloader is **not a hardened network isolation or untrusted URL security gateway**.
- Offline tests cover program logic, not current third-party network availability. The source sites might change independently.

## Tests

```bash
python -m unittest -v test_imageforge.py
```

13 offline tests cover filename safety, private-URL filtering, WallpapersCraft link extraction, extension detection, HTML response rejection, SHA-256 duplicate handling, minimum resolution, exact 1080p verification, Wikimedia creator/licence parsing, Google legacy setup and API parsing, gallery escaping, and non-destructive validation.

## Dependencies

- `requests` for HTTP, session pooling, retries, streaming
- `beautifulsoup4` for parsing WallpapersCraft HTML and metadata
- `Pillow` to validate downloaded images, formats and pixel resolution
- `ddgs` for general, multi-engine image search (used only for web mode)

## Reference documentation

- [Wikimedia Commons MediaWiki API](https://commons.wikimedia.org/wiki/Commons:API/MediaWiki)
- [MediaWiki API:Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)
- [DDGS Python image search](https://github.com/deedy5/ddgs)
- [Google Custom Search JSON API closure notice](https://developers.google.com/custom-search/v1/overview)
- [WallpapersCraft](https://wallpaperscraft.com/)
