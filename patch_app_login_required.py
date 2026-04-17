"""Patch app.py so the sentient_ext init call never NameErrors when login_required isn't imported.

Usage:
  py patch_app_login_required.py path/to/app.py

It replaces the last argument in sentient_ext.init_sentient(..., login_required)
with globals().get('login_required', (lambda f: f)).
"""

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: py patch_app_login_required.py path/to/app.py")
        return 2

    p = Path(sys.argv[1])
    if not p.exists():
        print(f"File not found: {p}")
        return 2

    txt = p.read_text(encoding="utf-8")

    # Match the init call line (or wrapped across whitespace) and replace trailing login_required.
    # We only touch calls that literally pass 'login_required' as the last argument.
    pattern = re.compile(
        r"(sentient_ext\.init_sentient\(.*?,\s*)(login_required)(\s*\)\s*)",
        re.DOTALL,
    )

    repl = r"\\1globals().get('login_required', (lambda f: f))\\3"

    new_txt, n = pattern.subn(repl, txt)
    if n == 0:
        print("No matching sentient_ext.init_sentient(..., login_required) call found. No changes made.")
        return 1

    p.write_text(new_txt, encoding="utf-8")
    print(f"Patched {p} (updated {n} call(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
