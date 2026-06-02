from __future__ import annotations

import html


def markdown_to_simple_html(markdown: str, title: str) -> str:
    body = []
    for line in markdown.splitlines():
        escaped = html.escape(line)
        if line.startswith("# "):
            body.append(f"<h1>{escaped[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{escaped[3:]}</h2>")
        elif line.startswith("### "):
            body.append(f"<h3>{escaped[4:]}</h3>")
        elif line.startswith("- "):
            body.append(f"<li>{escaped[2:]}</li>")
        elif not line.strip():
            body.append("")
        else:
            body.append(f"<p>{escaped}</p>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, "Noto Sans CJK SC", sans-serif; max-width: 920px; margin: 40px auto; line-height: 1.72; background: #f6f1e9; color: #20242a; }}
    h1, h2, h3 {{ color: #243447; }}
    li {{ margin: 4px 0; }}
  </style>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
"""

