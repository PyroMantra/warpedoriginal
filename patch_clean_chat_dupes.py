#!/usr/bin/env python3
import re
from pathlib import Path

tpl_dir = Path("templates")
if not tpl_dir.exists(): raise SystemExit("templates/ not found")

def scrub(html: str) -> str:
  # Remove stray standalone duplicates (outside the floating panel)
  html = re.sub(r'\s*<!--\s*Global Chat Panel\s*-->\s*<div id="chat-messages"></div>\s*', "\n", html, flags=re.I)
  html = re.sub(r'\s*<!--\s*Global Chat Panel\s*\(canonical\)\s*-->\s*<div id="chat-messages"></div>\s*', "\n", html, flags=re.I)
  html = re.sub(r'\s*<!--\s*Global Chat Hover Button\s*-->\s*<div id="chat-popover-messages"></div>\s*', "\n", html, flags=re.I)
  html = re.sub(r'\s*<div id="chat-popover-messages"></div>\s*', "\n", html, flags=re.I)
  # Remove old FAB/popover remnants if any
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-fab"[\s\S]*?</div>','', html, flags=re.I)
  html = re.sub(r'<div[^>]*id\s*=\s*"chat-popover"[\s\S]*?</div>','', html, flags=re.I)
  # Keep only one #global-chat — remove extras if duplicated
  parts = re.split(r'(<div[^>]*id\s*=\s*"global-chat"[^>]*>[\s\S]*?</div>)', html, flags=re.I)
  if len(parts) > 3:
    first = parts[1]
    rest = "".join(parts[2:])
    rest = re.sub(r'(<div[^>]*id\s*=\s*"global-chat"[^>]*>[\s\S]*?</div>)', '', rest, flags=re.I)
    html = parts[0] + first + rest
  return html

changed = 0
for f in tpl_dir.rglob("*.html"):
  txt = f.read_text(encoding="utf-8", errors="ignore")
  new = scrub(txt)
  if new != txt:
    f.with_suffix(f.suffix + ".bak_dupechat").write_text(txt, encoding="utf-8")
    f.write_text(new, encoding="utf-8")
    print("fixed", f)
    changed += 1
print("templates cleaned:", changed)
