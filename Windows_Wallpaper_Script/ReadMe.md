# Spotlight Wallpaper Manager

A safe, modern, and idempotent Python utility for extracting high-resolution images from the Windows Spotlight cache, validating them with Pillow, removing duplicates, classifying them by orientation, and organising them into a clean wallpaper archive.

The program treats the Windows Spotlight cache as **read-only**. It does not rename, modify, or delete Microsoft's original cached files.

---

## Features

- Automatically detects the Windows Spotlight asset directory
- Extracts valid images without modifying the original cache
- Detects image formats from file contents rather than filename extensions
- Validates images using Pillow
- Rejects corrupted or unsupported files
- Filters low-resolution images
- Classifies wallpapers as:
  - Desktop / landscape
  - Mobile / portrait
  - Square
- Handles EXIF image orientation
- Uses SHA-256 hashing for exact duplicate detection
- Generates deterministic filenames
- Maintains a persistent `manifest.json` archive index
- Uses atomic file copying
- Verifies copied files after writing
- Supports concurrent image inspection
- Supports repeated scans without generating duplicate files
- Includes dry-run mode
- Includes verbose diagnostic logging
- Includes continuous watch mode
- Allows custom source and destination directories
- Configurable resolution thresholds
- Configurable worker count
- Graceful error handling
- Command-line interface
- No destructive operations on the Windows Spotlight cache

---

# Why This Version?

The original implementation copied every Spotlight asset into another directory, renamed files to `.jpg`, checked for only specific image widths, and then moved files according to hardcoded resolutions.

That approach works for some older Spotlight assets, but it has several limitations.

This version replaces those assumptions with actual image inspection.

Instead of assuming:

```text
1920 pixels wide = desktop
1080 pixels wide = mobile
```

classification now uses the actual orientation:

```text
width > height  -> desktop
height > width  -> mobile
width == height -> square
```

It also detects the actual encoded image format before selecting the filename extension.

---

# Architecture

The program follows roughly this pipeline:

```text
Windows Spotlight Cache
        |
        v
Enumerate Assets
        |
        v
Parallel Image Inspection
        |
        +---- Invalid / non-image --------> Ignore
        |
        +---- Too small ------------------> Ignore
        |
        v
Image Validation
        |
        v
EXIF Orientation Handling
        |
        v
Resolution Filtering
        |
        v
SHA-256 Hashing
        |
        v
Duplicate Detection
        |
        v
Orientation Classification
        |
        +---- Landscape --> desktop/
        |
        +---- Portrait ---> mobile/
        |
        +---- Square -----> square/
        |
        v
Atomic Copy
        |
        v
Checksum Verification
        |
        v
manifest.json
```

---

# Requirements

## Operating System

Designed primarily for Windows systems using Windows Spotlight.

The program may technically run on other operating systems when supplied with a custom source directory, but automatic Spotlight cache discovery is Windows-specific.

## Python

Python 3.10 or newer is recommended.

Check your version:

```powershell
python --version
```

or:

```powershell
py --version
```

## Dependencies

The only external Python dependency is Pillow.

Install it with:

```powershell
py -m pip install --upgrade Pillow
```

or:

```bash
python -m pip install --upgrade Pillow
```

---

# Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
```

Enter the project directory:

```bash
cd YOUR_REPOSITORY
```

Install Pillow:

```bash
python -m pip install Pillow
```

Then run:

```bash
python spotlight_wallpaper_manager_v2.py
```

On Windows you can also use:

```powershell
py spotlight_wallpaper_manager_v2.py
```

---

# Default Spotlight Location

The program automatically searches for the normal Windows Spotlight cache:

```text
%LOCALAPPDATA%\Packages\
Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy\
LocalState\Assets
```

Which normally resolves to something similar to:

```text
C:\Users\YourName\AppData\Local\Packages\
Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy\
LocalState\Assets
```

No modifications are performed inside this directory.

---

# Basic Usage

Run a single Spotlight scan:

```powershell
py spotlight_wallpaper_manager_v2.py
```

The program will:

1. Locate the Spotlight cache
2. Inspect every cached asset
3. Detect valid images
4. Validate the image data
5. Read the logical image dimensions
6. Reject images below the configured resolution threshold
7. Calculate a SHA-256 checksum
8. Detect previously archived images
9. Classify new images by orientation
10. Copy new wallpapers into the archive
11. Verify the copied file
12. Update `manifest.json`

---

# Output Structure

By default the program creates a `Wallpapers` directory beside the script.

Example:

```text
project/
│
├── spotlight_wallpaper_manager_v2.py
│
└── Wallpapers/
    │
    ├── desktop/
    │   ├── spotlight_1920x1080_6a5ca69a2b8ae826.jpg
    │   └── spotlight_2560x1440_e54f72ce4bd21714.jpg
    │
    ├── mobile/
    │   ├── spotlight_1080x1920_487dc54963f13db5.jpg
    │   └── spotlight_1440x2560_12fe038a934a27ec.jpg
    │
    ├── square/
    │   └── spotlight_1200x1200_dfa2371687128842.jpg
    │
    └── manifest.json
```

---

# Deterministic Filenames

Extracted wallpapers use a filename generated from:

- Image dimensions
- First 16 characters of its SHA-256 checksum
- Actual detected image format

Example:

```text
spotlight_1920x1080_6a5ca69a2b8ae826.jpg
```

This provides several advantages:

- Filenames remain stable between scans
- Duplicate images do not create duplicate files
- Files can be identified without relying on Microsoft's cache filenames
- Collisions are extremely unlikely

---

# Dry Run

Before copying anything, inspect what the program would do:

```powershell
py spotlight_wallpaper_manager_v2.py --dry-run
```

For detailed output:

```powershell
py spotlight_wallpaper_manager_v2.py --dry-run --verbose
```

Dry-run mode performs image analysis without creating the wallpaper archive.

---

# Verbose Mode

Enable diagnostic information:

```powershell
py spotlight_wallpaper_manager_v2.py --verbose
```

or:

```powershell
py spotlight_wallpaper_manager_v2.py -v
```

Verbose logging can show why individual cache entries were skipped.

Examples include:

```text
not a regular file
```

```text
unsupported image format
```

```text
below minimum resolution
```

```text
unidentified image
```

---

# Continuous Watch Mode

The application can continuously monitor the Spotlight cache.

Run:

```powershell
py spotlight_wallpaper_manager_v2.py --watch
```

By default it rescans every:

```text
60 seconds
```

Stop watch mode with:

```text
Ctrl+C
```

---

# Custom Watch Interval

For example, scan every five minutes:

```powershell
py spotlight_wallpaper_manager_v2.py --watch --interval 300
```

Scan every 30 seconds:

```powershell
py spotlight_wallpaper_manager_v2.py --watch --interval 30
```

The minimum supported interval is one second.

---

# Custom Output Directory

Choose another wallpaper archive location:

```powershell
py spotlight_wallpaper_manager_v2.py --output "D:\Spotlight Wallpapers"
```

Example:

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --output "C:\Users\Kai\Pictures\Spotlight"
```

---

# Custom Source Directory

A different asset directory can also be supplied:

```powershell
py spotlight_wallpaper_manager_v2.py --source "C:\Some\Asset\Folder"
```

This can also make the image extraction engine useful for testing or processing exported Spotlight caches.

---

# Resolution Filtering

By default, images must have at least:

```text
Longest edge:  1000 pixels
Shortest edge: 600 pixels
```

This is significantly more flexible than checking for one specific resolution.

For example, all of the following can qualify:

```text
1920 × 1080
2560 × 1440
3840 × 2160
1080 × 1920
1440 × 2560
1200 × 1200
```

provided that they satisfy the configured limits.

---

# Changing the Minimum Resolution

Example:

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --min-long-edge 1920 ^
    --min-short-edge 1080
```

This effectively limits extraction to roughly Full-HD-class imagery or larger.

For a more permissive filter:

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --min-long-edge 800 ^
    --min-short-edge 480
```

---

# Parallel Processing

Image inspection can run concurrently.

The application automatically chooses a reasonable number of workers, limited to a maximum of eight by default.

You can override it:

```powershell
py spotlight_wallpaper_manager_v2.py --workers 4
```

For example:

```powershell
py spotlight_wallpaper_manager_v2.py --workers 8
```

The parallel stage performs tasks such as:

- Image validation
- Metadata extraction
- Resolution inspection
- Hash generation

Disk performance will normally become the limiting factor before CPU performance.

---

# Duplicate Detection

Every accepted image receives a SHA-256 hash.

For example:

```text
6a5ca69a2b8ae826...
```

Before an image is copied, the program checks whether that hash already exists in the archive.

This provides exact binary duplicate detection.

Therefore repeated execution is safe:

```powershell
py spotlight_wallpaper_manager_v2.py
py spotlight_wallpaper_manager_v2.py
py spotlight_wallpaper_manager_v2.py
```

Existing wallpapers should not be copied again.

This property makes the extraction process **idempotent**.

---

# Manifest Database

The application maintains:

```text
Wallpapers/manifest.json
```

The manifest stores metadata about archived images.

A record can contain information such as:

```json
{
  "sha256": "6a5ca69a2b8ae826...",
  "width": 1920,
  "height": 1080,
  "image_format": "JPEG",
  "extension": ".jpg",
  "category": "desktop",
  "bytes": 483294,
  "source": "C:\\Users\\...\\Assets\\...",
  "destination": "C:\\...\\Wallpapers\\desktop\\spotlight_1920x1080_6a5ca69a2b8ae826.jpg",
  "archived_utc": "2026-09-13T13:00:00+00:00"
}
```

This allows subsequent scans to rapidly identify already archived files.

---

# Manifest Recovery

If `manifest.json` is:

- Missing
- Invalid
- Truncated
- Corrupted

the application can rebuild archive knowledge from existing deterministic filenames and SHA-256 verification.

A broken manifest therefore does not automatically destroy or invalidate the wallpaper archive.

---

# Image Validation

Unlike the original implementation, the program does not assume that every Spotlight cache entry is a JPEG.

The cache contains files without conventional extensions.

Pillow examines the underlying binary data to determine whether a file represents a supported image.

The program effectively performs:

```python
with Image.open(path) as probe:
    probe.verify()
```

The file is then reopened for metadata inspection because Pillow's verification process invalidates the original decoder state.

---

# EXIF Orientation

Some image formats can store camera or display orientation in EXIF metadata.

The application uses:

```python
ImageOps.exif_transpose(...)
```

before orientation classification.

This helps ensure that:

```text
desktop
mobile
square
```

are based on the intended visible orientation rather than only the raw encoded dimensions.

---

# Supported Formats

Common Pillow-supported formats can be archived.

Explicit mappings include:

```text
JPEG -> .jpg
PNG  -> .png
WEBP -> .webp
BMP  -> .bmp
TIFF -> .tif
GIF  -> .gif
AVIF -> .avif
```

Windows Spotlight assets are commonly JPEG-based, but the implementation deliberately avoids relying on that assumption.

---

# Atomic Copies

Images are not copied directly into their final filename.

Instead the program first creates a temporary file:

```text
wallpaper.jpg.part
```

After the copy succeeds, it performs an atomic replacement into the final destination.

Conceptually:

```text
Source
  |
  v
Temporary .part file
  |
  v
Successful copy
  |
  v
Atomic rename
  |
  v
Final wallpaper
```

If the program is unexpectedly interrupted during copying, this greatly reduces the chance of a partially written file appearing as a legitimate wallpaper.

---

# Post-Copy Verification

After an image has been copied, the program calculates its SHA-256 hash again.

The resulting hash must match the source checksum.

Conceptually:

```text
SHA256(source)
      ==
SHA256(destination)
```

If verification fails, the destination file is removed and an error is reported.

This adds an additional integrity layer over a normal filesystem copy.

---

# Safety

The application deliberately avoids destructive interaction with the Spotlight cache.

It does **not**:

```text
rename Spotlight assets
delete Spotlight assets
change Spotlight extensions
overwrite Spotlight assets
move Spotlight assets
modify Spotlight metadata
```

The source directory is effectively treated as:

```text
READ ONLY
```

Only the program's own output directory is modified.

---

# Error Handling

Individual corrupted cache entries should not terminate an entire scan.

The program handles common conditions such as:

- Invalid image data
- Unsupported formats
- Missing source directory
- Permission failures
- Corrupt manifest
- Files disappearing during inspection
- Invalid command-line values
- Failed copies
- Failed checksum verification
- Interrupted watch mode

---

# Command-Line Reference

Display help:

```powershell
py spotlight_wallpaper_manager_v2.py --help
```

Available options:

```text
--source PATH
```

Override the Windows Spotlight source directory.

```text
--output PATH
```

Change the archive destination.

```text
--min-long-edge PIXELS
```

Set the minimum longest edge.

Default:

```text
1000
```

```text
--min-short-edge PIXELS
```

Set the minimum shortest edge.

Default:

```text
600
```

```text
--workers COUNT
```

Set concurrent inspection workers.

```text
--dry-run
```

Analyse the cache without copying images.

```text
--watch
```

Continuously monitor for newly downloaded wallpapers.

```text
--interval SECONDS
```

Set the watch-mode rescan interval.

Default:

```text
60
```

```text
-v
--verbose
```

Enable detailed diagnostics.

```text
--version
```

Display the application version.

---

# Examples

## Normal Scan

```powershell
py spotlight_wallpaper_manager_v2.py
```

---

## Safe Preview

```powershell
py spotlight_wallpaper_manager_v2.py --dry-run
```

---

## Detailed Preview

```powershell
py spotlight_wallpaper_manager_v2.py --dry-run --verbose
```

---

## Watch Spotlight

```powershell
py spotlight_wallpaper_manager_v2.py --watch
```

---

## Watch Every 5 Minutes

```powershell
py spotlight_wallpaper_manager_v2.py --watch --interval 300
```

---

## Archive Only Larger Images

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --min-long-edge 1920 ^
    --min-short-edge 1080
```

---

## Use Eight Workers

```powershell
py spotlight_wallpaper_manager_v2.py --workers 8
```

---

## Custom Destination

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --output "D:\Wallpaper Archive"
```

---

## Combine Options

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --output "D:\Spotlight Archive" ^
    --min-long-edge 1920 ^
    --min-short-edge 1080 ^
    --workers 8 ^
    --verbose
```

---

# Example Output

A successful scan may look similar to:

```text
14:08:12 | INFO     | Scanning 84 cached asset(s)
14:08:13 | INFO     | Copying 1920x1080 -> Wallpapers\desktop\spotlight_1920x1080_6a5ca69a2b8ae826.jpg
14:08:13 | INFO     | Copying 1080x1920 -> Wallpapers\mobile\spotlight_1080x1920_a8e4f4129e3a85a7.jpg

========================================================================
Spotlight Wallpaper Manager 2.0.0 - scan complete
========================================================================
Scanned assets : 84
Valid images   : 27
New copies     : 2
Duplicates     : 25
Too small      : 18
Non-images     : 39
Errors         : 0
========================================================================
```

A later run might report:

```text
========================================================================
Spotlight Wallpaper Manager 2.0.0 - scan complete
========================================================================
Scanned assets : 84
Valid images   : 27
New copies     : 0
Duplicates     : 27
Too small      : 18
Non-images     : 39
Errors         : 0
========================================================================
```

This is expected and demonstrates that duplicate detection is working.

---

# Comparison With the Original Version

| Capability | Original | Version 2 |
|---|---:|---:|
| Copy Spotlight assets | Yes | Yes |
| Auto-detect cache | Partial | Yes |
| Modify source files | Possible | No |
| Detect real image format | No | Yes |
| Image verification | Basic | Yes |
| SHA-256 deduplication | No | Yes |
| Persistent manifest | No | Yes |
| Atomic copies | No | Yes |
| Post-copy verification | No | Yes |
| Parallel scanning | No | Yes |
| EXIF orientation handling | No | Yes |
| Landscape classification | Hardcoded width | Orientation based |
| Portrait classification | Hardcoded width | Orientation based |
| Square images | No | Yes |
| Configurable resolution | No | Yes |
| Dry-run mode | No | Yes |
| Watch mode | No | Yes |
| Verbose diagnostics | Minimal | Yes |
| Custom source | No | Yes |
| Custom output | No | Yes |
| Deterministic filenames | No | Yes |
| Idempotent scans | No | Yes |
| Graceful manifest recovery | N/A | Yes |

---

# Original Logic Issue Fixed

The original script included logic similar to:

```python
if width == 1920:
    move_to_desktop()

if width == 1080:
    move_to_mobile()
else:
    close()
```

Because the second `if` owns the `else`, a `1920`-pixel image could be moved during the first condition and then continue into the second condition's `else`.

The new implementation eliminates this class of problem by performing a single orientation classification:

```python
if width > height:
    return "desktop"

if height > width:
    return "mobile"

return "square"
```

---

# Another Original Error Fixed

The original extraction routine could perform something equivalent to:

```python
try:
    im = Image.open(path)
except IOError:
    print("Not an image")

if im.size[0] != 1920:
    ...
```

If `Image.open()` failed, `im` might never have been assigned.

The upgraded implementation returns immediately from failed inspections and never accesses an uninitialised image object.

---

# Development Philosophy

The project follows several principles:

### Non-destructive

Never alter Microsoft's Spotlight cache.

### Deterministic

The same source image should generate the same destination name.

### Idempotent

Running the utility repeatedly should not produce duplicate archives.

### Verifiable

Image integrity should be checked rather than assumed.

### Recoverable

A damaged manifest should not destroy the wallpaper collection.

### Concurrent

Independent asset inspection can happen in parallel.

### Extensible

The extraction engine is separated enough that future classification or metadata features can be added without rewriting the complete application.

---

# Potential Future Features

Possible future versions could add:

- Perceptual hashing for visually identical images
- Duplicate detection across resized variants
- Windows notification integration
- System tray operation
- Automatic desktop wallpaper rotation
- Spotlight metadata extraction
- Location recognition
- OCR for embedded text
- Image similarity clustering
- SQLite archive database
- Searchable wallpaper catalogue
- Automatic favourite system
- Wallpaper scoring
- Multi-monitor wallpaper management
- GUI interface
- Thumbnail browser
- Web dashboard
- HEIF/HEIC support where available
- Automatic archive compression
- Metadata export to CSV
- Metadata export to SQLite
- Windows Task Scheduler integration
- Content-aware categorisation
- Local AI image tagging
- Semantic image search
- Duplicate detection using perceptual hashes such as pHash
- Colour-palette extraction
- Dominant-colour indexing
- Automatic dark/light wallpaper classification
- Resolution-aware monitor matching

---

# Troubleshooting

## Spotlight Folder Not Found

You may see:

```text
Spotlight asset folder was not found
```

First make sure Windows Spotlight is enabled.

The expected cache is normally below:

```text
%LOCALAPPDATA%\Packages\
Microsoft.Windows.ContentDeliveryManager_cw5n1h2txyewy\
LocalState\Assets
```

You can also manually provide an asset directory:

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --source "C:\Path\To\Assets"
```

---

## Pillow Is Missing

If you see:

```text
ModuleNotFoundError: No module named 'PIL'
```

install Pillow:

```powershell
py -m pip install Pillow
```

---

## Permission Denied

Try running from a directory where your account has write access.

You can also specify another destination:

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --output "%USERPROFILE%\Pictures\Spotlight"
```

Administrator privileges should not normally be required.

---

## No New Wallpapers Appear

Run:

```powershell
py spotlight_wallpaper_manager_v2.py --verbose
```

The wallpapers may already exist in the archive.

If so, the summary should show an increased:

```text
Duplicates
```

count.

---

## Everything Is Being Rejected as Too Small

Reduce the resolution requirements:

```powershell
py spotlight_wallpaper_manager_v2.py ^
    --min-long-edge 800 ^
    --min-short-edge 450
```

---

# Testing

A useful synthetic test directory can contain:

```text
landscape image
portrait image
square image
small image
duplicate image
non-image file
corrupted image
```

A successful first scan should archive only valid images that satisfy the resolution threshold.

A second scan should produce no additional copies and classify the existing valid images as duplicates.

---

# Security Considerations

Although Spotlight assets originate from Windows infrastructure, the program still treats cached data as untrusted input.

Images are therefore:

1. Opened through Pillow
2. Verified before processing
3. Reopened after verification
4. Filtered by format
5. Inspected before copying

No cached asset is executed.

The utility only reads files as image data.

---

# Performance

The program uses a `ThreadPoolExecutor` during image analysis.

This is appropriate because much of the workload involves filesystem operations such as:

```text
reading files
opening images
reading metadata
hashing data
```

The default worker count is based on the machine's CPU count but capped at eight.

For very fast SSDs, increasing the worker count may improve processing speed.

For slow disks, excessive concurrency can reduce performance.

---

# Project Structure

A minimal repository can use:

```text
Spotlight-Wallpaper-Manager/
│
├── spotlight_wallpaper_manager_v2.py
├── README.md
├── requirements.txt
├── LICENSE
└── .gitignore
```

Suggested `requirements.txt`:

```text
Pillow>=10.0
```

Suggested `.gitignore`:

```gitignore
__pycache__/
*.pyc
*.pyo
*.pyd

.venv/
venv/
env/

Wallpapers/
*.part

.idea/
.vscode/

.DS_Store
Thumbs.db
desktop.ini
```

---

# License

Choose a licence appropriate for your project.

For an open-source utility, the MIT License is a common option.

Example:

```text
MIT License

Copyright (c) 2026 Kai Piper
```

Add the complete licence text to:

```text
LICENSE
```

if you decide to publish the project under MIT.

---

# Disclaimer

This project is an independent utility and is not affiliated with, endorsed by, or maintained by Microsoft.

Windows and Windows Spotlight are trademarks or services associated with Microsoft.

The program relies on implementation details of Windows Spotlight that may change in future Windows releases.

Always keep important wallpaper archives backed up independently of the Spotlight cache.

---

# Author

**Kai Piper**

GitHub:

```text
kai9987kai
```

---

# Version

Current major implementation:

```text
Spotlight Wallpaper Manager 2.0.0
```

The project transforms a small Windows Spotlight extraction script into a safer archive pipeline with image verification, deterministic deduplication, concurrency, integrity checking, persistent metadata, and continuous monitoring.
