---
name: memer-ai-media-mark-cleaner
description: Clean and inspect file-level metadata in images and videos, including C2PA/JUMBF, XMP, creator software, prompt/workflow, and publishing fields, then produce HTML, TXT, and JSON verification reports. Use when a user asks to scan or clean media metadata, review removed traces, batch-process media, or launch the MemeR-AI graphical cleaner.
---

# MemeR-AI图文视频印记数据清理

Use the bundled deterministic cleaner. It preserves source files and writes cleaned copies plus verification reports.

## Run

For Codex-driven cleanup, run:

```powershell
python "<skill-dir>\scripts\run_cleaner.py" "<input-file-or-folder>" -o "<output-folder>"
```

Pass multiple input paths when needed. For inspection without writing cleaned files, add `--scan-only`.

After cleanup:

1. Read `clean_report.json` and summarize the number of files, removed traces, remaining traces, and errors.
2. Give the user the local path to `clean_report.html`; open it when they ask to view the report.
3. Call out every `REMAINS` item. MP4 `handler_name`, `HandlerDescription`, or codec `encoder` values may be structural defaults rather than AI provenance.

For the interactive desktop application, run:

```powershell
python "<skill-dir>\scripts\run_cleaner.py" --gui
```

The GUI supports file/folder selection, output selection, progress, per-file removed/remaining traces, and opening the HTML report.

The bundled self-contained executables target Windows. On macOS or Linux, the launcher falls back to the Python source and requires Pillow, FFmpeg/ffprobe, and ExifTool to be available locally.

## Boundaries

- Describe this as file-level metadata hygiene and false-positive risk inspection.
- Do not claim it removes invisible watermarks, visual/audio model signals, platform detection, or disclosure obligations.
- Do not overwrite source files.
- Do not treat a zero remaining-field count as proof that content is non-AI.
- Supported images: JPEG, PNG, WebP, BMP, TIFF. Supported videos: MP4, MOV, M4V, AVI, MKV, WebM.

Read [references/report-schema.md](references/report-schema.md) only when interpreting report fields or troubleshooting a result.
