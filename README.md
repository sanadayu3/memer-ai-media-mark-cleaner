# MemeR-AI图文视频印记数据清理

面向 Windows 与 Codex 的本地图片/视频文件层元数据清理工具。支持图形界面、批量处理、清理前后复查，以及 HTML/TXT/JSON 三种报告。

> 本工具用于文件层元数据卫生与误标风险排查，不承诺绕过 TikTok 或其他平台的 AI 识别，不删除隐形水印，也不改变平台披露义务。

## 一键安装 Codex Skill

在 PowerShell 中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/sanadayu3/memer-ai-media-mark-cleaner/main/install.ps1 | iex"
```

安装完成后重新打开 Codex，直接提出“清理这些图片/视频的文件层元数据并显示报告”，或显式调用：

```text
$memer-ai-media-mark-cleaner
```

安装脚本会下载最新 Release、校验 SHA-256，并在覆盖旧版前创建时间戳备份。

## 下载独立 EXE

- [下载 Windows 便携版](https://github.com/sanadayu3/memer-ai-media-mark-cleaner/releases/latest/download/MemeR-AI%E5%9B%BE%E6%96%87%E8%A7%86%E9%A2%91%E5%8D%B0%E8%AE%B0%E6%95%B0%E6%8D%AE%E6%B8%85%E7%90%86-portable.zip)
- [查看最新 Release](https://github.com/sanadayu3/memer-ai-media-mark-cleaner/releases/latest)

解压后双击 `MemeR-AI图文视频印记数据清理.exe`。移动时请保留整个文件夹，不能只移动 EXE。

## 功能

- 图片：JPEG、PNG、WebP、BMP、TIFF。
- 视频：MP4、MOV、M4V、AVI、MKV、WebM。
- 检查并清理 EXIF、XMP、QuickTime、JUMBF、C2PA、Content Credentials。
- 识别生成软件、模型、提示词、工作流、种子及常见发布字段。
- 视频重编码为 MP4 / H.264 / AAC，并移除章节、字幕轨、数据轨与普通 metadata。
- 每个文件显示 `REMOVED`（已清除）和 `REMAINS`（复查残留）。
- 生成可视化 `clean_report.html`、审计记录 `clean_report.txt` 和结构化 `clean_report.json`。
- 内置 FFmpeg、ffprobe 与 ExifTool，无需另行安装。

## 输出示例

### Seedance：清理 C2PA/JUMBF、模型名与参数字段

![Seedance C2PA removed traces](docs/images/removed-seedance-c2pa.png)

### OpenAI/ChatGPT：识别 Content Credentials 与生成器字段

![OpenAI C2PA detected traces](docs/images/detected-openai-c2pa.png)

### Google：识别 C2PA Core Generator 与生成描述

![Google C2PA detected traces](docs/images/detected-google-c2pa.jpg)

截图中的字段仅用于演示文件层扫描与复查输出，不代表对任何平台检测结果的保证。

## 报告说明

处理完成后，输出目录包含：

- 清理后的图片或 MP4 视频。
- `clean_report.html`：浏览器可打开的可视化报告。
- `clean_report.txt`：逐项列出已清除与残留痕迹。
- `clean_report.json`：供 Codex 或自动化读取。

MP4 容器可能重新生成 `handler_name`、`HandlerDescription` 或 codec `encoder` 等结构字段。报告会将其列为残留，但它们本身不等于 AI 来源证明。

## 仓库内容

- `skill/`：Skill 指令、清理核心与 Codex 启动器源码。
- `install.ps1`：带校验与旧版本备份的一键安装器。
- `docs/images/`：真实输出示例。
- GitHub Releases：完整 Codex Skill ZIP 与 Windows EXE 便携包。

## 第三方组件

发行包内含 FFmpeg/ffprobe 与 ExifTool。它们分别遵循各自项目许可；本仓库中的 Skill 指令与启动脚本不改变这些第三方许可。
