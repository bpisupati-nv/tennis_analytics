"""Render report.md to a single self-contained report.html (images inlined)."""
import base64
import os
import re

import markdown

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
text = open(os.path.join(here, "report.md")).read()
body = markdown.markdown(text, extensions=["tables", "fenced_code"])


def inline(match):
    path = os.path.join(here, match.group(1))
    data = base64.b64encode(open(path, "rb").read()).decode()
    return f'src="data:image/jpeg;base64,{data}"'


body = re.sub(r'src="([^"]+\.jpg)"', inline, body)
style = """body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;line-height:1.5;color:#222}
table{border-collapse:collapse;margin:1em 0;font-size:0.9em}th,td{border:1px solid #ccc;padding:4px 8px;text-align:center}
th{background:#f2f2f2}td:first-child,th:first-child{text-align:left}img{max-width:100%;border:1px solid #ddd;margin:0.5em 0}
code,pre{background:#f6f6f6}pre{padding:0.8em;overflow:auto}"""
html = f"<!doctype html><html><head><meta charset='utf-8'><title>Court calibration improvements</title><style>{style}</style></head><body>{body}</body></html>"
open(os.path.join(here, "report.html"), "w").write(html)
print("report.html", os.path.getsize(os.path.join(here, "report.html")) // 1024, "KB")
