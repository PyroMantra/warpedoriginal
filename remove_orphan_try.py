#!/usr/bin/env python3
import re
from pathlib import Path

app_path = Path("app.py").resolve()
if not app_path.exists():
    print("ERROR: app.py not found in", app_path.parent)
    raise SystemExit(1)

src_lines = app_path.read_text(encoding="utf-8", errors="ignore").splitlines()

def indent(s):
    return len(s) - len(s.lstrip(" "))

n = len(src_lines)
remove_try_at = set()

# Pass 1: mark orphan "try:" lines (no except/finally at same indent before dedent)
i = 0
while i < n:
    line = src_lines[i]
    if re.match(r'^\s*try:\s*$', line):
        lvl = indent(line)
        j = i + 1
        found_pair = False
        while j < n:
            ln = src_lines[j]
            if ln.strip() == "":
                j += 1
                continue
            lvl_j = indent(ln)
            if lvl_j < lvl:
                break
            if lvl_j == lvl and re.match(r'^\s*(except\b|finally:)\s*', ln):
                found_pair = True
                break
            j += 1
        if not found_pair:
            remove_try_at.add(i)
    i += 1

# Pass 2: rebuild file, dropping orphan "try:" and commenting orphan except/finally
new_lines = []
open_try = {}  # try counts per indent

for idx, line in enumerate(src_lines):
    il = indent(line)
    for k in list(open_try.keys()):
        if k > il:
            del open_try[k]

    if idx in remove_try_at:
        continue

    if re.match(r'^\s*try:\s*$', line):
        open_try[il] = open_try.get(il, 0) + 1
        new_lines.append(line)
        continue

    if re.match(r'^\s*except\b', line) or re.match(r'^\s*finally:\s*$', line):
        if open_try.get(il, 0) > 0:
            open_try[il] -= 1
            new_lines.append(line)
        else:
            new_lines.append("# " + line)  # orphan; neutralize
        continue

    new_lines.append(line)

patched = "\n".join(new_lines) + ("\n" if src_lines and not src_lines[-1].endswith("\n") else "")

backup = app_path.with_suffix(".py.bak3")
backup.write_text("\n".join(src_lines), encoding="utf-8")
app_path.write_text(patched, encoding="utf-8")

print("Sanitized app.py")
print(" - Removed", len(remove_try_at), "orphan 'try:' line(s)")
print("Backup:", backup)
