#!/usr/bin/env python3
import re
from pathlib import Path

APP = Path("app.py")
src = APP.read_text(encoding="utf-8", errors="ignore")

def block_bounds(s, start_idx):
    # start at beginning of decorator line
    start = s.rfind("\n", 0, start_idx)
    start = 0 if start == -1 else start + 1
    # end at next decorator or __main__ guard or EOF
    next_decos = [s.find("\n@app.route(", start_idx+1), s.find("\n@bp.route(", start_idx+1)]
    next_guard = s.find("\nif __name__", start_idx+1)
    candidates = [i for i in next_decos+[next_guard] if i != -1]
    end = min(candidates) if candidates else len(s)
    return start, end

# 1) Keep first @app.route("/login/google")
pat_login_google_route = re.compile(r'@app\.route\(\s*[\'"]/login/google[\'"]([^)]*)\)\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', re.S)
matches = list(pat_login_google_route.finditer(src))
if matches:
    # keep the first
    first = matches[0]
    keep_start, keep_end = block_bounds(src, first.start())
    # remove subsequent ones
    for m in reversed(matches[1:]):
        s, e = block_bounds(src, m.start())
        src = src[:s] + src[e:]

# 2) Remove any OTHER routes that explicitly set endpoint="login_google" (even if path differs),
#    except the one we kept above.
pat_endpoint_dup = re.compile(r'@app\.route\(\s*[^)]*endpoint\s*=\s*[\'"]login_google[\'"][^)]*\)\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', re.S)
matches2 = list(pat_endpoint_dup.finditer(src))
# If the kept block exists, protect it by position
protected_span = (keep_start, keep_end) if matches else None
for m in reversed(matches2):
    s, e = block_bounds(src, m.start())
    if protected_span and not (s >= protected_span[0] and e <= protected_span[1]):
        src = src[:s] + src[e:]

# 3) If no /login/google remains (edge case), add a canonical one.
if not pat_login_google_route.search(src):
    add_block = """@app.route("/login/google", endpoint="login_google")
def login_google():
    redirect_uri = url_for("auth_google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)
"""
    guard = "\nif __name__"
    gpos = src.find(guard)
    src = (src.rstrip() + "\n\n" + add_block + "\n") if gpos == -1 else (src[:gpos] + add_block + "\n" + src[gpos:])

APP.write_text(src, encoding="utf-8")
print("Deduped /login/google. Kept one endpoint: login_google.")
