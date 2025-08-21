#!/usr/bin/env python3
import re
from pathlib import Path

root = Path(".").resolve()
tpl_dir = root / "templates"

def fix_welcome_text(text: str) -> str:
    lines = text.splitlines()
    out = []
    for ln in lines:
        if re.search(r"\bWelcome\b", ln, flags=re.I):
            # Fix previous bad replacement artifacts
            ln = re.sub(r"\b1\s*\{\{\s*current_user_name\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\\1\s*\{\{\s*current_user_name\s*\}\}", "{{ current_user_name }}", ln)

            # Replace "Welcome, None" (literal or templated)
            ln = re.sub(r"(Welcome\s*,\s*)(?:None|\{\{\s*None\s*\}\})", r"\1{{ current_user_name }}", ln, flags=re.I)
            # Replace "Welcome, {{ anything }}"
            ln = re.sub(r"(Welcome\s*,\s*)\{\{[^}]+\}\}", r"\1{{ current_user_name }}", ln)
            # Map common username expressions
            ln = re.sub(r"\{\{\s*session\.get\(\s*['\"]username['\"]\s*\)\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\{\{\s*session\.username\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\{\{\s*user\.username\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\{\{\s*username\s*\}\}", "{{ current_user_name }}", ln)
        out.append(ln)
    return "\n".join(out)

def remove_duplicate_brand(text: str) -> str:
    original = text

    # 1) Remove duplicate brand anchors: <a ...>Across the Planes</a>
    anch_pat = re.compile(r"(?i)<a\b[^>]*>\s*Across the Planes\s*</a>")
    matches = list(anch_pat.finditer(text))
    if len(matches) > 1:
        # Keep the first, remove the rest
        for m in reversed(matches[1:]):
            s, e = m.span()
            text = text[:s] + "" + text[e:]

    # 2) Also remove duplicate plain text occurrences (not inside <title>)
    # Count occurrences and remove from the second onward.
    # We do this lightly, only outside <title>...</title>.
    def kill_plain_dupes(t: str) -> str:
        out = []
        brand_seen = 0
        for line in t.splitlines():
            # Skip <title> lines entirely
            if re.search(r"(?i)<\s*title\b", line):
                out.append(line)
                continue
            # Count and remove additional plain text instances in this line
            parts = re.split(r"(?i)(Across the Planes)", line)
            if len(parts) > 1:
                rebuilt = []
                i = 0
                while i < len(parts):
                    seg = parts[i]
                    if i+1 < len(parts) and re.match(r"(?i)Across the Planes", parts[i+1]):
                        # seg + brand + next seg
                        rebuilt.append(seg)
                        brand_seen += 1
                        if brand_seen == 1:
                            rebuilt.append(parts[i+1])  # keep first
                        else:
                            # drop duplicate brand text
                            pass
                        i += 2
                    else:
                        rebuilt.append(seg)
                        i += 1
                out.append("".join(rebuilt))
            else:
                out.append(line)
        return "\n".join(out)

    text = kill_plain_dupes(text)
    return text

changed = []

if tpl_dir.exists():
    for html in tpl_dir.rglob("*.html"):
        txt = html.read_text(encoding="utf-8", errors="ignore")
        original = txt
        txt = fix_welcome_text(txt)
        txt = remove_duplicate_brand(txt)
        if txt != original:
            # backup
            html.with_suffix(".html.bak_brandfix").write_text(original, encoding="utf-8")
            html.write_text(txt, encoding="utf-8")
            changed.append(str(html.relative_to(root)))

if changed:
    print("Updated templates:")
    for c in changed:
        print(" -", c)
else:
    print("No template changes were necessary (already clean).")
