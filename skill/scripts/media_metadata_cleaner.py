#!/usr/bin/env python3
"""Clean file-level media metadata and generate verification reports."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import ExifTags, Image, UnidentifiedImageError
except ImportError:
    ExifTags = None
    Image = None
    UnidentifiedImageError = Exception


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
SUPPORTED_EXTS = IMAGE_EXTS | VIDEO_EXTS

RISK_PATTERNS = {
    "C2PA / Content Credentials": [r"c2pa", r"jumbf", r"content.?credentials?", r"manifest"],
    "XMP / creator metadata": [r"\bxmp\b", r"dc:", r"photoshop", r"creator", r"software", r"encoder"],
    "AI generator hints": [
        r"midjourney", r"stable.?diffusion", r"\bdall.?e\b", r"openai", r"synthid",
        r"comfyui", r"automatic1111", r"invokeai", r"firefly", r"runway", r"pika", r"kling",
    ],
    "prompt / workflow fields": [
        r"prompt", r"negative.?prompt", r"parameters", r"workflow", r"seed", r"\bsampler\b", r"model",
    ],
    "publish metadata": [
        r"creation_time", r"com\.apple\.quicktime", r"handler_name", r"handlerdescription",
        r"title", r"comment", r"description", r"keywords?", r"artist", r"copyright",
    ],
}


@dataclass
class FlaggedItem:
    category: str
    key: str
    value: str


@dataclass
class ScanResult:
    path: str
    media_type: str
    metadata_entries: int = 0
    flagged: list[FlaggedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class CleanResult:
    source: str
    output: str | None
    media_type: str
    before: ScanResult
    after: ScanResult | None = None
    removed_traces: list[FlaggedItem] = field(default_factory=list)
    remaining_traces: list[FlaggedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def preview_value(value: Any, limit: int = 260) -> str:
    text = f"<{len(value)} bytes>" if isinstance(value, bytes) else str(value)
    text = " ".join(text.replace("\x00", " ").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def app_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
        if getattr(sys, "_MEIPASS", None):
            dirs.append(Path(sys._MEIPASS))
    here = Path(__file__).resolve().parent
    dirs.extend([here, here.parent])
    return dirs


def find_tool(name: str) -> str | None:
    candidates: list[Path] = []
    for base in app_dirs():
        candidates.extend([
            base / f"{name}.exe",
            base / "vendor" / "ffmpeg" / "bin" / f"{name}.exe",
            base / "vendor" / "exiftool" / "bin" / f"{name}.exe",
            base.parent / "vendor" / "ffmpeg" / "bin" / f"{name}.exe",
            base.parent / "vendor" / "exiftool" / "bin" / f"{name}.exe",
        ])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    direct = shutil.which(name)
    if direct:
        try:
            return str(Path(direct).resolve(strict=True))
        except OSError:
            return direct
    return None


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(cmd, **kwargs)
    if check and proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"Command failed: {cmd[0]}")
    return proc


def media_type_for(path: Path) -> str | None:
    if path.suffix.lower() in IMAGE_EXTS:
        return "image"
    if path.suffix.lower() in VIDEO_EXTS:
        return "video"
    return None


def collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and media_type_for(candidate):
                key = os.path.normcase(str(candidate.resolve()))
                if key not in seen:
                    seen.add(key)
                    files.append(candidate.resolve())
    return sorted(files)


def flatten_metadata(prefix: str, value: Any) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            rows.extend(flatten_metadata(f"{prefix}.{key}" if prefix else str(key), child))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(flatten_metadata(f"{prefix}[{index}]", child))
    else:
        rows.append((prefix, preview_value(value)))
    return rows


def logical_marker(item: FlaggedItem) -> tuple[str, str, str]:
    leaf = re.split(r"[.:]", item.key.lower())[-1]
    leaf = re.sub(r"[^a-z0-9_]+", "", leaf)
    return item.category.lower(), leaf, item.value.strip().lower()


def flag_metadata(metadata: dict[str, Any]) -> list[FlaggedItem]:
    flagged: list[FlaggedItem] = []
    seen: set[tuple[str, str, str]] = set()
    for key, value in flatten_metadata("", metadata):
        haystack = f"{key} {value}".lower()
        for category, patterns in RISK_PATTERNS.items():
            if any(re.search(pattern, haystack, re.IGNORECASE) for pattern in patterns):
                item = FlaggedItem(category, key, value)
                marker = logical_marker(item)
                if marker not in seen:
                    seen.add(marker)
                    flagged.append(item)
                break
    return flagged


def scan_with_exiftool(path: Path) -> tuple[dict[str, Any], list[str]]:
    tool = find_tool("exiftool")
    if not tool:
        return {}, ["ExifTool unavailable; deep metadata scan was skipped."]
    try:
        proc = run_command([tool, "-a", "-G1", "-s", "-j", str(path)])
        payload = json.loads(proc.stdout or "[]")
        return ({"exiftool": payload[0]} if payload else {}), []
    except Exception as exc:
        return {}, [f"ExifTool scan failed: {exc}"]


def scan_image(path: Path) -> tuple[dict[str, Any], list[str]]:
    if Image is None:
        return {}, ["Pillow unavailable; image pixel re-save is unavailable."]
    try:
        with Image.open(path) as image:
            metadata: dict[str, Any] = {
                "format": image.format,
                "mode": image.mode,
                "size": f"{image.width}x{image.height}",
                "info": {key: preview_value(value) for key, value in image.info.items()},
            }
            exif = image.getexif()
            if exif:
                tags = ExifTags.TAGS if ExifTags else {}
                metadata["exif"] = {tags.get(tag, str(tag)): preview_value(value) for tag, value in exif.items()}
            return {"pillow": metadata}, []
    except (UnidentifiedImageError, OSError) as exc:
        return {}, [f"Image scan failed: {exc}"]


def scan_video(path: Path) -> tuple[dict[str, Any], list[str]]:
    tool = find_tool("ffprobe")
    if not tool:
        return {}, ["ffprobe unavailable; video stream scan was skipped."]
    try:
        proc = run_command([
            tool, "-hide_banner", "-v", "error", "-show_format", "-show_streams",
            "-print_format", "json", str(path),
        ])
        data = json.loads(proc.stdout or "{}")
        streams = [
            {
                "index": stream.get("index"),
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "tags": stream.get("tags", {}),
            }
            for stream in data.get("streams", [])
        ]
        return {"ffprobe": {"format_tags": data.get("format", {}).get("tags", {}), "streams": streams}}, []
    except Exception as exc:
        return {}, [f"ffprobe scan failed: {exc}"]


def scan_file(path: Path) -> ScanResult:
    media_type = media_type_for(path) or "unsupported"
    metadata, errors = scan_with_exiftool(path)
    extra, extra_errors = scan_image(path) if media_type == "image" else scan_video(path)
    metadata.update(extra)
    errors.extend(extra_errors)
    return ScanResult(
        path=str(path),
        media_type=media_type,
        metadata_entries=len(flatten_metadata("", metadata)),
        flagged=flag_metadata(metadata),
        errors=errors,
    )


def unique_output_path(output_dir: Path, source: Path, media_type: str) -> Path:
    suffix = ".mp4" if media_type == "video" else source.suffix.lower()
    first = output_dir / f"{source.stem}_clean{suffix}"
    if not first.exists():
        return first
    for index in range(2, 10000):
        candidate = output_dir / f"{source.stem}_clean_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot create a unique output name for {source.name}")


def clean_image(source: Path, output: Path) -> None:
    if Image is None:
        raise RuntimeError("Pillow is unavailable.")
    with Image.open(source) as image:
        if getattr(image, "is_animated", False):
            raise RuntimeError("Animated images are not supported; convert to video first.")
        clean = image.copy()
        clean.info = {}
        ext = output.suffix.lower()
        if ext in {".jpg", ".jpeg"}:
            if clean.mode not in {"RGB", "L"}:
                clean = clean.convert("RGB")
            clean.save(output, "JPEG", quality=95, optimize=True, progressive=True)
        elif ext == ".png":
            clean.save(output, "PNG", optimize=True)
        elif ext == ".webp":
            if clean.mode == "P":
                clean = clean.convert("RGBA")
            clean.save(output, "WEBP", quality=95, method=6)
        elif ext in {".tif", ".tiff"}:
            clean.save(output, "TIFF", compression="tiff_deflate")
        elif ext == ".bmp":
            clean.save(output, "BMP")
        else:
            raise RuntimeError(f"Unsupported image type: {ext}")


def clean_video(source: Path, output: Path) -> None:
    tool = find_tool("ffmpeg")
    if not tool:
        raise RuntimeError("ffmpeg is unavailable.")
    run_command([
        tool, "-hide_banner", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "-1", "-map_chapters", "-1",
        "-fflags", "+bitexact", "-dn", "-sn", "-metadata", "encoder=",
        "-metadata:s:v", "handler_name=", "-metadata:s:a", "handler_name=",
        "-c:v", "libx264", "-flags:v", "+bitexact", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level", "4.1", "-movflags", "+faststart",
        "-c:a", "aac", "-flags:a", "+bitexact", "-b:a", "128k", str(output),
    ])


def exiftool_scrub(output: Path) -> None:
    tool = find_tool("exiftool")
    if not tool:
        return
    run_command([
        tool, "-all=", "-XMP:all=", "-QuickTime:all=", "-Keys:all=",
        "-UserData:all=", "-JUMBF:all=", "-overwrite_original", str(output),
    ])


def clean_file(source: Path, output_dir: Path) -> CleanResult:
    media_type = media_type_for(source) or "unsupported"
    before = scan_file(source)
    result = CleanResult(str(source), None, media_type, before)
    if media_type not in {"image", "video"}:
        result.errors.append("Unsupported media type.")
        return result
    output_dir.mkdir(parents=True, exist_ok=True)
    output = unique_output_path(output_dir, source, media_type)
    try:
        clean_image(source, output) if media_type == "image" else clean_video(source, output)
        exiftool_scrub(output)
        result.output = str(output)
        result.after = scan_file(output)
        after_markers = {logical_marker(item) for item in result.after.flagged}
        result.removed_traces = [item for item in before.flagged if logical_marker(item) not in after_markers]
        result.remaining_traces = list(result.after.flagged)
    except Exception as exc:
        result.errors.append(str(exc))
        if output.exists():
            output.unlink()
    return result


def scan_to_dict(scan: ScanResult | None) -> dict[str, Any] | None:
    if scan is None:
        return None
    return {
        "path": scan.path,
        "media_type": scan.media_type,
        "metadata_entries": scan.metadata_entries,
        "flagged": [asdict(item) for item in scan.flagged],
        "errors": scan.errors,
    }


def result_to_dict(result: CleanResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "output": result.output,
        "media_type": result.media_type,
        "before": scan_to_dict(result.before),
        "after": scan_to_dict(result.after),
        "removed_traces": [asdict(item) for item in result.removed_traces],
        "remaining_traces": [asdict(item) for item in result.remaining_traces],
        "errors": result.errors,
    }


def text_report(results: list[CleanResult]) -> str:
    sections: list[str] = []
    for result in results:
        lines = [
            f"Source: {result.source}", f"Output: {result.output or '-'}", f"Media type: {result.media_type}",
            f"Removed traces: {len(result.removed_traces)}",
        ]
        lines.extend(
            [f"  REMOVED | {item.category} | {item.key} = {item.value}" for item in result.removed_traces]
            or ["  none detected before cleanup"]
        )
        lines.append(f"Remaining flagged traces: {len(result.remaining_traces)}")
        lines.extend(
            [f"  REMAINS | {item.category} | {item.key} = {item.value}" for item in result.remaining_traces]
            or ["  none"]
        )
        lines.extend(f"  ERROR | {error}" for error in result.errors)
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"


def trace_rows(items: list[FlaggedItem], status: str) -> str:
    if not items:
        return '<tr><td colspan="4" class="empty">无</td></tr>'
    return "".join(
        "<tr>"
        f'<td><span class="badge {status.lower()}">{html.escape(status)}</span></td>'
        f"<td>{html.escape(item.category)}</td><td>{html.escape(item.key)}</td>"
        f"<td class=\"value\">{html.escape(item.value)}</td></tr>"
        for item in items
    )


def html_report(results: list[CleanResult]) -> str:
    total = len(results)
    succeeded = sum(not result.errors for result in results)
    removed = sum(len(result.removed_traces) for result in results)
    remaining = sum(len(result.remaining_traces) for result in results)
    cards: list[str] = []
    for result in results:
        state = "ok" if not result.errors and not result.remaining_traces else "warn"
        status = "完成" if not result.errors else "失败"
        errors = "".join(f"<li>{html.escape(error)}</li>" for error in result.errors)
        error_block = f'<div class="errors"><strong>错误</strong><ul>{errors}</ul></div>' if errors else ""
        cards.append(f"""
        <section class="file-card {state}">
          <div class="file-head">
            <div><span class="file-type">{html.escape(result.media_type.upper())}</span>
            <h2>{html.escape(Path(result.source).name)}</h2></div>
            <span class="status {state}">{status}</span>
          </div>
          <dl><dt>源文件</dt><dd>{html.escape(result.source)}</dd>
          <dt>输出文件</dt><dd>{html.escape(result.output or '-')}</dd></dl>
          <div class="split">
            <div><h3>已清除 <b>{len(result.removed_traces)}</b></h3>
              <table><thead><tr><th>状态</th><th>类别</th><th>字段</th><th>值</th></tr></thead>
              <tbody>{trace_rows(result.removed_traces, 'REMOVED')}</tbody></table></div>
            <div><h3>复查残留 <b>{len(result.remaining_traces)}</b></h3>
              <table><thead><tr><th>状态</th><th>类别</th><th>字段</th><th>值</th></tr></thead>
              <tbody>{trace_rows(result.remaining_traces, 'REMAINS')}</tbody></table></div>
          </div>{error_block}
        </section>""")
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MemeR-AI图文视频印记数据清理报告</title>
<style>
:root{{--bg:#f4f6f8;--panel:#fff;--ink:#18212b;--muted:#64717d;--line:#dce2e7;--green:#16794b;--green-bg:#e7f5ed;--amber:#9a5b00;--amber-bg:#fff3d6;--red:#a12b2b;--red-bg:#fdeaea}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Segoe UI","Microsoft YaHei",sans-serif;letter-spacing:0}}
.top{{background:#172a3a;color:#fff;padding:34px 24px 48px}}.wrap{{max-width:1280px;margin:auto}}h1{{margin:0;font-size:30px}}.sub{{color:#c9d4dc;margin-top:7px}}
.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:-26px}}.stat{{background:#fff;border:1px solid var(--line);padding:18px;border-radius:8px;box-shadow:0 6px 18px #12202c12}}.stat b{{display:block;font-size:28px}}.stat span{{color:var(--muted)}}
.notice{{margin:18px 0;padding:12px 14px;border-left:4px solid #376d91;background:#eaf3f9}}.file-card{{background:var(--panel);border:1px solid var(--line);border-top:4px solid var(--green);border-radius:8px;margin:16px 0;padding:18px;overflow:hidden}}.file-card.warn{{border-top-color:#d08a20}}
.file-head{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}h2{{margin:4px 0 12px;font-size:20px;overflow-wrap:anywhere}}.file-type{{color:var(--muted);font-size:12px;font-weight:700}}.status,.badge{{display:inline-block;border-radius:999px;padding:3px 9px;font-weight:700;font-size:12px}}.status.ok,.badge.removed{{background:var(--green-bg);color:var(--green)}}.status.warn,.badge.remains{{background:var(--amber-bg);color:var(--amber)}}
dl{{display:grid;grid-template-columns:80px 1fr;gap:4px 12px;margin:0 0 16px}}dt{{color:var(--muted)}}dd{{margin:0;overflow-wrap:anywhere}}.split{{display:grid;gap:18px}}h3{{font-size:15px;margin:12px 0 7px}}h3 b{{font-size:18px}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}th,td{{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#f7f9fa;color:#53616c;font-size:12px}}th:nth-child(1){{width:90px}}th:nth-child(2){{width:180px}}th:nth-child(3){{width:28%}}.value{{font-family:Consolas,monospace;font-size:12px}}.empty{{text-align:center;color:var(--muted)}}.errors{{margin-top:12px;padding:10px;background:var(--red-bg);color:var(--red)}}footer{{color:var(--muted);padding:18px 0 32px}}
@media(max-width:760px){{.stats{{grid-template-columns:1fr 1fr}}.file-head{{display:block}}table{{display:block;overflow:auto}}th:nth-child(n){{width:auto}}dl{{grid-template-columns:1fr}}}}
</style></head><body><header class="top"><div class="wrap"><h1>MemeR-AI图文视频印记数据清理报告</h1><div class="sub">生成于 {html.escape(generated)}</div></div></header>
<main class="wrap"><div class="stats"><div class="stat"><b>{total}</b><span>处理文件</span></div><div class="stat"><b>{succeeded}</b><span>成功完成</span></div><div class="stat"><b>{removed}</b><span>已清除痕迹</span></div><div class="stat"><b>{remaining}</b><span>复查残留</span></div></div>
<div class="notice">本报告仅验证文件层元数据。它不检测或删除隐形水印、内容特征、平台模型信号，也不改变平台披露义务。</div>{''.join(cards)}</main>
<footer class="wrap">MemeR-AI图文视频印记数据清理 · 本地报告</footer></body></html>"""


def write_reports(results: list[CleanResult], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "clean_report.json",
        "text": output_dir / "clean_report.txt",
        "html": output_dir / "clean_report.html",
    }
    paths["json"].write_text(json.dumps([result_to_dict(result) for result in results], ensure_ascii=False, indent=2), "utf-8")
    paths["text"].write_text(text_report(results), "utf-8-sig")
    paths["html"].write_text(html_report(results), "utf-8")
    return paths


def print_result(result: CleanResult) -> None:
    print(f"FILE: {result.source}")
    print(f"OUTPUT: {result.output or '-'}")
    print(f"REMOVED_COUNT: {len(result.removed_traces)}")
    for item in result.removed_traces:
        print(f"  REMOVED | {item.category} | {item.key} = {item.value}")
    print(f"REMAINING_COUNT: {len(result.remaining_traces)}")
    for item in result.remaining_traces:
        print(f"  REMAINS | {item.category} | {item.key} = {item.value}")
    for error in result.errors:
        print(f"  ERROR | {error}")


def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("MemeR-AI图文视频印记数据清理")
    root.geometry("940x700")
    root.minsize(760, 560)
    selected: list[Path] = []
    output_var = tk.StringVar(value=str(Path.cwd() / "metadata_cleaned"))
    status_var = tk.StringVar(value="添加图片、视频或文件夹后开始清理。")
    latest_report: list[Path | None] = [None]

    outer = ttk.Frame(root, padding=14)
    outer.pack(fill="both", expand=True)
    toolbar = ttk.Frame(outer)
    toolbar.pack(fill="x")
    add_files = ttk.Button(toolbar, text="添加文件")
    add_folder = ttk.Button(toolbar, text="添加文件夹")
    clear = ttk.Button(toolbar, text="清空列表")
    add_files.pack(side="left")
    add_folder.pack(side="left", padx=(8, 0))
    clear.pack(side="left", padx=(8, 0))
    count = ttk.Label(toolbar, text="0 个文件")
    count.pack(side="right")

    list_frame = ttk.Frame(outer)
    list_frame.pack(fill="x", pady=(10, 0))
    file_list = tk.Listbox(list_frame, height=9, selectmode="extended")
    list_scroll = ttk.Scrollbar(list_frame, command=file_list.yview)
    file_list.configure(yscrollcommand=list_scroll.set)
    file_list.pack(side="left", fill="both", expand=True)
    list_scroll.pack(side="right", fill="y")

    output_frame = ttk.Frame(outer)
    output_frame.pack(fill="x", pady=(10, 0))
    ttk.Label(output_frame, text="输出目录").pack(side="left")
    output_entry = ttk.Entry(output_frame, textvariable=output_var)
    output_entry.pack(side="left", fill="x", expand=True, padx=8)
    choose_output = ttk.Button(output_frame, text="选择目录")
    choose_output.pack(side="right")

    actions = ttk.Frame(outer)
    actions.pack(fill="x", pady=(10, 0))
    start = ttk.Button(actions, text="开始清理")
    start.pack(side="left")
    open_report = ttk.Button(actions, text="打开可视化报告", state="disabled")
    open_report.pack(side="left", padx=(8, 0))
    progress = ttk.Progressbar(actions, mode="indeterminate")
    progress.pack(side="left", fill="x", expand=True, padx=(10, 0))
    ttk.Label(outer, textvariable=status_var).pack(fill="x", pady=(8, 4))

    log_frame = ttk.Frame(outer)
    log_frame.pack(fill="both", expand=True)
    log = tk.Text(log_frame, state="disabled", wrap="word", font=("Consolas", 10))
    log_scroll = ttk.Scrollbar(log_frame, command=log.yview)
    log.configure(yscrollcommand=log_scroll.set)
    log.pack(side="left", fill="both", expand=True)
    log_scroll.pack(side="right", fill="y")

    def append(message: str) -> None:
        log.configure(state="normal")
        log.insert("end", message.rstrip() + "\n")
        log.see("end")
        log.configure(state="disabled")

    def refresh() -> None:
        file_list.delete(0, "end")
        for path in selected:
            file_list.insert("end", str(path))
        count.configure(text=f"{len(selected)} 个文件")

    def add(paths: list[Path]) -> None:
        existing = {os.path.normcase(str(path)) for path in selected}
        was_empty = not selected
        new_files = collect_files(paths)
        for path in new_files:
            key = os.path.normcase(str(path))
            if key not in existing:
                existing.add(key)
                selected.append(path)
        if selected and was_empty:
            output_var.set(str(selected[0].parent / "metadata_cleaned"))
        refresh()

    def choose_files_action() -> None:
        files = filedialog.askopenfilenames(
            title="选择图片或视频",
            filetypes=[("支持的媒体", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.mp4 *.mov *.m4v *.avi *.mkv *.webm"), ("所有文件", "*.*")],
        )
        if files:
            add([Path(path) for path in files])

    def choose_folder_action() -> None:
        folder = filedialog.askdirectory(title="选择媒体文件夹")
        if folder:
            add([Path(folder)])

    def clear_action() -> None:
        selected.clear()
        refresh()

    def output_action() -> None:
        folder = filedialog.askdirectory(title="选择输出目录", initialdir=output_var.get())
        if folder:
            output_var.set(folder)

    widgets = (add_files, add_folder, clear, choose_output, start, output_entry)

    def busy(value: bool) -> None:
        for widget in widgets:
            widget.configure(state="disabled" if value else "normal")
        progress.start(12) if value else progress.stop()

    def show_one(result: CleanResult, index: int, total: int) -> None:
        append(f"\n[{index}/{total}] {result.source}")
        append(f"输出: {result.output or '-'}")
        append(f"已清除痕迹: {len(result.removed_traces)}")
        for item in result.removed_traces:
            append(f"  REMOVED | {item.category} | {item.key} = {item.value}")
        append(f"复查残留: {len(result.remaining_traces)}")
        for item in result.remaining_traces:
            append(f"  REMAINS | {item.category} | {item.key} = {item.value}")
        for error in result.errors:
            append(f"  ERROR | {error}")

    def finish(results: list[CleanResult], reports: dict[str, Path] | None, error: str | None) -> None:
        busy(False)
        if reports:
            latest_report[0] = reports["html"]
            open_report.configure(state="normal")
            append(f"\n可视化报告: {reports['html']}")
            append(f"审计记录: {reports['text']}")
        if error:
            append(f"报告写入失败: {error}")
        failed = sum(bool(result.errors) for result in results) + int(bool(error))
        status_var.set(f"处理完成：{len(results) - failed} 成功，{failed} 需检查。")
        if reports and not failed:
            if messagebox.askyesno("处理完成", "清理和复查已完成。现在打开可视化报告吗？"):
                webbrowser.open(reports["html"].resolve().as_uri())
        else:
            messagebox.showwarning("处理完成", "部分项目需要检查，请查看窗口日志。")

    def start_action() -> None:
        if not selected:
            messagebox.showwarning("未选择文件", "请先添加图片、视频或文件夹。")
            return
        if not output_var.get().strip():
            messagebox.showwarning("未设置输出目录", "请选择输出目录。")
            return
        files = list(selected)
        output_dir = Path(output_var.get().strip()).expanduser().resolve()
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        append("范围：仅清理文件层元数据，不代表绕过平台 AI 识别或披露要求。")
        open_report.configure(state="disabled")
        latest_report[0] = None
        busy(True)

        def worker() -> None:
            results: list[CleanResult] = []
            for index, source in enumerate(files, 1):
                root.after(0, status_var.set, f"正在处理 {index}/{len(files)}: {source.name}")
                result = clean_file(source, output_dir)
                results.append(result)
                root.after(0, show_one, result, index, len(files))
            reports = None
            report_error = None
            try:
                reports = write_reports(results, output_dir)
            except Exception as exc:
                report_error = str(exc)
            root.after(0, finish, results, reports, report_error)

        threading.Thread(target=worker, daemon=True).start()

    add_files.configure(command=choose_files_action)
    add_folder.configure(command=choose_folder_action)
    clear.configure(command=clear_action)
    choose_output.configure(command=output_action)
    start.configure(command=start_action)
    open_report.configure(command=lambda: latest_report[0] and webbrowser.open(latest_report[0].resolve().as_uri()))
    root.mainloop()
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean file-level image/video metadata and generate verification reports.")
    parser.add_argument("paths", nargs="+", type=Path, help="Input media files or folders.")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("metadata_cleaned"))
    parser.add_argument("--scan-only", action="store_true", help="Scan without writing cleaned files.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else argv
    if not raw:
        return run_gui()
    args = parse_args(raw)
    files = collect_files(args.paths)
    if not files:
        print("No supported media files found.", file=sys.stderr)
        return 2
    if args.scan_only:
        for path in files:
            scan = scan_file(path)
            print(f"FILE: {scan.path}\nFLAGGED_COUNT: {len(scan.flagged)}")
            for item in scan.flagged:
                print(f"  FLAGGED | {item.category} | {item.key} = {item.value}")
        return 0
    results: list[CleanResult] = []
    for path in files:
        result = clean_file(path, args.output_dir.expanduser().resolve())
        results.append(result)
        print_result(result)
    reports = write_reports(results, args.output_dir.expanduser().resolve())
    print(f"REPORT_HTML: {reports['html'].resolve()}")
    print(f"REPORT_TEXT: {reports['text'].resolve()}")
    print(f"REPORT_JSON: {reports['json'].resolve()}")
    return 1 if any(result.errors for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
