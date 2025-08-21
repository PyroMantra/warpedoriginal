#!/usr/bin/env python3
import re
from pathlib import Path
from textwrap import dedent

root = Path(".").resolve()
tpl_dir = root / "templates"
static_dir = root / "static"
static_dir.mkdir(exist_ok=True)

# 1) Ensure chat CSS forces messages ABOVE the input (even if DOM order is wrong)
css_path = static_dir / "chat.css"
append_block = dedent("""
/* --- Chat layout enforcement (messages above input) --- */
#global-chat { display: flex; flex-direction: column; }
#chat-messages { order: 0; flex: 1 1 auto; overflow-y: auto; }
#chat-form     { order: 1; }
/* --- end layout enforcement --- */
""").strip("\n") + "\n"

if css_path.exists():
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    if "#chat-messages { order:" not in css or "#chat-form     { order:" not in css:
        css_path.with_suffix(".css.bak_order").write_text(css, encoding="utf-8")
        css = css.rstrip() + "\n\n" + append_block
        css_path.write_text(css, encoding="utf-8")
else:
    # Minimal CSS if file missing
    css = dedent("""
    #global-chat { position:fixed; right:16px; top:110px; width:340px; max-height:calc(100vh - 140px);
      background:rgba(30,30,30,.92); border:1px solid rgba(255,255,255,.12); border-radius:12px; display:flex; flex-direction:column; overflow:hidden; z-index:9999;}
    .chat-header { padding:10px 12px; font-weight:700; background:linear-gradient(90deg,#c14916,#8f2c12); color:#fff; cursor:move;}
    #chat-messages { padding:10px; gap:6px; display:flex; flex-direction:column; }
    #chat-form { padding:10px; border-top:1px solid rgba(255,255,255,.1); display:flex; flex-direction:column; gap:8px;}
    #chat-input { min-height:64px; background:rgba(0,0,0,.3); color:#fff; border:1px solid rgba(255,255,255,.15); border-radius:8px; padding:8px 10px;}
    #chat-send { background:#c14916; color:#fff; border:none; border-radius:8px; padding:10px 12px; cursor:pointer;}
    """).strip("\n") + "\n" + append_block
    css_path.write_text(css, encoding="utf-8")

# 2) Normalize brand links: make any "Across the Planes" anchor go to home
def fix_brand_links(file: Path):
    t = file.read_text(encoding="utf-8", errors="ignore")
    o = t

    # Replace anchors whose inner text (possibly with nested spans) contains "Across the Planes"
    # We keep all other attributes, but we remove/replace href to home.
    # Works across lines thanks to DOTALL.
    def repl(m):
        open_tag_attrs = m.group("attrs") or ""
        inner = m.group("inner")
        # strip any href=... from attrs
        attrs_no_href = re.sub(r'\s+href\s*=\s*(["\']).*?\1', '', open_tag_attrs, flags=re.I)
        new_attrs = f' href="{{ url_for(\'home\') }}"' + attrs_no_href
        return f"<a{new_attrs}>{inner}</a>"

    pattern = re.compile(
        r"<a(?P<attrs>[^>]*)>(?P<inner>.*?Across\s*the\s*Planes.*?)</a>",
        re.I | re.S
    )
    t = pattern.sub(repl, t)

    # Also catch a common navbar-brand case where text is split by tags (already handled),
    # but if the brand is NOT a link, we won't force-wrap it. Most navbars use <a>.
    if t != o:
        file.with_suffix(file.suffix + ".bak_brandlink").write_text(o, encoding="utf-8")
        file.write_text(t, encoding="utf-8")
        return True
    return False

brand_fixed = []
if tpl_dir.exists():
    for f in tpl_dir.rglob("*.html"):
        try:
            # only bother with files that mention the brand at all
            txt = f.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"Across\s*the\s*Planes", txt, re.I):
                if fix_brand_links(f):
                    brand_fixed.append(str(f.relative_to(root)))
        except Exception:
            pass

print("Chat CSS updated to force messages above input.")
if brand_fixed:
    print("Brand anchors updated to point to home in:")
    for x in brand_fixed:
        print(" -", x)
else:
    print("No brand anchors needed changes (or none found).")
