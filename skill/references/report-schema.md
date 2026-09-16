# Report interpretation

The cleaner writes three equivalent reports into the selected output folder:

- `clean_report.html`: self-contained visual report for people.
- `clean_report.txt`: UTF-8 audit log for quick reading.
- `clean_report.json`: structured report for Codex and automation.

Each JSON result contains:

- `source` and `output`: original and cleaned file paths.
- `before` and `after`: scan summaries, flagged fields, and scanner warnings.
- `removed_traces`: flagged fields present before cleanup and absent after cleanup.
- `remaining_traces`: flagged fields still detected after cleanup.
- `errors`: failures that prevented or weakened cleanup.

`removed_traces` and `remaining_traces` are risk-oriented findings, not a dump of every technical property. Resolution, duration, bitrate, codecs, and similar playback properties are intentionally excluded.

ExifTool and Pillow/ffprobe can observe the same physical field through different paths. The cleaner merges equivalent findings by category, terminal field name, and value before counting them.

MP4 muxers may recreate structural values such as `handler_name`, `HandlerDescription`, and codec `encoder`. Report these as remaining container defaults; do not present them as proof of AI provenance.

The report does not inspect invisible watermark signals or platform-side behavioral and content models.
