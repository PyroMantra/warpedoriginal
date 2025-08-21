#!/usr/bin/env python3
import re
from pathlib import Path

root = Path(".").resolve()
tpl_dir = root / "templates"
changed = []

def strip_leading_cg_ones(text: str) -> str:
    """
    Remove any stray `1` or `\1` immediately before a Jinja {{ ... }} expression.
    Handles `1{{ current_user_name }}`, `\1{{ current_user_name }}`, and the same
    pattern with any variable, anywhere in the file.
    """
    # Generic: any \1 or 1 directly before a Jinja expression
    #   - Optional whitespace between 1 and {{
    #   - Keep just the Jinja expression
    text = re.sub(r"(?:\\1|(?<!\w)1)\s*(\{\{[^}]+\}\})", r"\1", text)
    return text

def normalize_welcome(text: str) -> str:
    """
    Ensure welcome lines render the nice display name variable and not 'None' or raw session refs.
    """
    lines = text.splitlines()
    out = []
    for ln in lines:
        if re.search(r"\bWelcome\b", ln, flags=re.I):
            # Replace 'Welcome, None' and 'Welcome, {{ anything }}' with current_user_name
            ln = re.sub(r"(Welcome\s*,\s*)(?:None|\{\{\s*None\s*\}\})", r"\1{{ current_user_name }}", ln, flags=re.I)
            ln = re.sub(r"(Welcome\s*,\s*)\{\{[^}]+\}\}", r"\1{{ current_user_name }}", ln)
            # Common username variants -> current_user_name
            ln = re.sub(r"\{\{\s*session\.get\(\s*['\"]username['\"]\s*\)\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\{\{\s*session\.username\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\{\{\s*user\.username\s*\}\}", "{{ current_user_name }}", ln)
            ln = re.sub(r"\{\{\s*username\s*\}\}", "{{ current_user_name }}", ln)
        out.append(ln)
    return "\n".join(out)

def remove_duplicate_brand_across_project():
    """
    Keep the very first non-<title> 'Across the Planes' occurrence across the entire project,
    remove all later duplicates (both anchors and plain text). This avoids duplicate brand in
    base + include scenarios.
    """
    brand_seen = False
    for html in sorted(tpl_dir.rglob("*.html")):
        text = html.read_text(encoding="utf-8", errors="ignore")
        original = text

        # 1) Remove duplicate anchors in this file (keep first within file)
        anch_pat = re.compile(r"(?i)<a\b[^>]*>\s*Across the Planes\s*</a>")
        matches = list(anch_pat.finditer(text))
        if len(matches) > 1:
            # keep first, remove the rest
            for m in reversed(matches[1:]):
                s, e = m.span()
                text = text[:s] + "" + text[e:]

        # 2) Project-wide plain-text removal outside <title>…</title>
        lines = text.splitlines()
        new_lines = []
        for ln in lines:
            if re.search(r"(?i)<\s*title\b", ln):
                new_lines.append(ln)
                continue
            # Split around the brand text and keep the first overall (project-wide)
            parts = re.split(r"(?i)(Across the Planes)", ln)
            if len(parts) > 1:
                rebuilt = []
                i = 0
                while i < len(parts):
                    seg = parts[i]
                    if i+1 < len(parts) and re.match(r"(?i)Across the Planes", parts[i+1]):
                        rebuilt.append(seg)
                        if not brand_seen:
                            rebuilt.append(parts[i+1])  # keep first across project
                            brand_seen = True
                        # else drop duplicates
                        i += 2
                    else:
                        rebuilt.append(seg)
                        i += 1
                new_lines.append("".join(rebuilt))
            else:
                new_lines.append(ln)
        new_text = "\n".join(new_lines)

        if new_text != original:
            html.with_suffix(".html.bak_brandclean").write_text(original, encoding="utf-8")
            html.write_text(new_text, encoding="utf-8")
            changed.append(str(html.relative_to(root)))

if not tpl_dir.exists():
    raise SystemExit("No templates/ directory found.")

# Process each template: remove leading '1' / '\1' artifacts and normalize welcome line.
for html in sorted(tpl_dir.rglob("*.html")):
    txt = html.read_text(encoding="utf-8", errors="ignore")
    original = txt
    txt = strip_leading_cg_ones(txt)
    txt = normalize_welcome(txt)
    if txt != original:
        html.with_suffix(".html.bak_onefix").write_text(original, encoding="utf-8")
        html.write_text(txt, encoding="utf-8")
        changed.append(str(html.relative_to(root)))

# Then do the cross-project brand de-duplication
remove_duplicate_brand_across_project()

if changed:
    print("Updated files:")
    for c in sorted(set(changed)):
        print(" -", c)
else:
    print("No changes were necessary.")
