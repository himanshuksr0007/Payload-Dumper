# AOSP Payload Dumper

A tool for extracting payload.bin files from Android OTA packages. Works on Windows, Linux, and macOS.

[Features](#features) • [Quick Start](#quick-start) • [Usage](#usage) • [FAQ](#faq)

---

## What is this?

A tool for extracting partition images (`.img` files) from `payload.bin` files found inside Android OTA/ROM zip files.

Has both a GUI and a command-line interface. You can extract all partitions or pick specific ones like `system`, `boot`, `vendor`.

**Useful if you're:**

- Making or maintaining custom ROMs
- Porting Android builds between devices
- Extracting `boot.img` for rooting
- Creating backups or recovery images

---

## Features

**Core:**

- Extracts all partition images from full OTA payloads
- Select specific partitions instead of extracting everything
- Handles ZIP files — automatically finds `payload.bin` inside
- Extract directly from HTTP/HTTPS/S3 without downloading first
- Supports BZ2, XZ/LZMA, Zstandard, and Brotli compressed payloads

**GUI:**

- Partition selector — loads available partitions from the manifest, multi-select supported
- Output directory is optional — defaults to the same folder as your payload file
- Real-time progress bar and extraction log
- Results tab showing extracted files and sizes
- Multi-threaded — stays responsive during extraction
- Remembers your last-used file paths

---

## Quick Start

### Windows Users (easiest way)

1. Download `PayloadDumper.exe` from [Releases](https://github.com/himanshuksr0007/aosp-payload-dumper/releases)
2. Run it (no installation needed)
3. Pick your `payload.bin` or `.zip` file
4. Optionally choose an output folder (defaults to same folder as the file)
5. Select partitions from the list, or leave "ALL" selected
6. Hit **Start Extraction**

### Linux/macOS or if you prefer running from source

```bash
# Clone the repo
git clone https://github.com/himanshuksr0007/aosp-payload-dumper.git
cd aosp-payload-dumper

# Install dependencies
pip install -r requirements.txt

# Generate protobuf files
protoc --python_out=. update_metadata.proto

# Launch GUI
python payload_gui.py

# Or use CLI
python payload_core.py your-payload.bin --out extracted/
```

---

## Usage

### How to extract

1. **Pick your file**
   - Click **Browse** next to "Payload/OTA File"
   - Select your `payload.bin` or `.zip`

2. **Choose output folder** _(optional)_
   - Click **Browse** next to "Output Directory"
   - If left empty, files are extracted to the same folder as your payload

3. **Select partitions**
   - Write the partition name you want to extract (seperated by comma for multiple partitions)
   - leave empty to extract all partitions
   - _example: boot,system,vendor_

4. **Extract**
   - Click **Start Extraction**
   - Watch progress in real-time

5. **Check results**
   - Switch to the **Results** tab
   - See what got extracted and file sizes
   - Click **Open Output Folder** to browse the files

## Building Your Own Executable

```bash
# Install PyInstaller
pip install pyinstaller

# Build
pyinstaller --onefile --windowed --name PayloadDumper --add-data "update_metadata_pb2.py;." payload_gui.py
```

Output will be in `dist/PayloadDumper.exe` (Windows) or `dist/PayloadDumper` (Linux/macOS).

---

## FAQ

**What Android versions work?**  
Any version that uses A/B (seamless) updates — Android 7.0 and newer. Tested on Android 10–16.

**Can I extract from full ROM zips?**  
Only if they contain `payload.bin` inside. Fastboot image zips and other formats won't work.

---

## Credits

Built by [himanshuksr0007](https://github.com/himanshuksr0007)

**Uses these libraries:**

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — GUI
- [protobuf](https://github.com/protocolbuffers/protobuf) — Payload parsing
- [brotli](https://github.com/google/brotli) — Brotli decompression
- [python-zstandard](https://github.com/indygreg/python-zstandard) — Zstandard decompression
- [fsspec](https://github.com/fsspec/filesystem_spec) — Remote file access

---

**Please star this repo if it helped you!**
