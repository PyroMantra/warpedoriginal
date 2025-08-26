
import os, re

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
APP_PY = os.path.join(PROJECT_ROOT, "app.py")
HEX_DIR = os.path.join(PROJECT_ROOT, "static", "hexes")

def log(msg): print(msg)

def ensure_hex_dir():
    os.makedirs(HEX_DIR, exist_ok=True)
    keep = os.path.join(HEX_DIR, ".keep")
    if not os.path.exists(keep):
        open(keep, "w").write("")

def ensure_hexes_template():
    src = os.path.join(os.path.dirname(__file__), "..", "templates", "hexes.html")
    dst = os.path.join(TEMPLATES_DIR, "hexes.html")
    if not os.path.exists(dst):
        with open(src, "r", encoding="utf-8") as f: html = f.read()
        with open(dst, "w", encoding="utf-8") as f: f.write(html)
        log("[OK] Created templates/hexes.html")
    else:
        log("[OK] templates/hexes.html already exists")

def ensure_route():
    if not os.path.exists(APP_PY):
        log(f"[WARN] app.py not found at {APP_PY}. Skipping route patch.")
        return
    with open(APP_PY, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    if "def hexes_gallery(" in content:
        log("[OK] Route already present in app.py")
        return
    if "import os" not in content:
        content = "import os\n" + content
    if "from flask import" in content:
        def add_import_token(src, token):
            if re.search(rf"from\s+flask\s+import\s+.*\b{token}\b", src):
                return src
            return re.sub(r"(from\s+flask\s+import\s+)([^\n]+)", lambda m: m.group(1) + m.group(2).strip() + f", {token}", src, count=1)
        content = add_import_token(content, "render_template")
        content = add_import_token(content, "url_for")
    else:
        content = "from flask import render_template, url_for\n" + content

    ROUTE = """
@app.route("/hexes")
def hexes_gallery():
    hex_dir = os.path.join(app.static_folder, "hexes")
    try:
        filenames = sorted([f for f in os.listdir(hex_dir)
                            if f.lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".gif", ".avif"))])
    except FileNotFoundError:
        filenames = []
    images = [(name, url_for("static", filename=f"hexes/{name}")) for name in filenames]
    return render_template("hexes.html", images=images)
"""
    content = content.rstrip() + "\n\n" + ROUTE
    with open(APP_PY, "w", encoding="utf-8") as f:
        f.write(content)
    log("[OK] Added /hexes route to app.py")

def clone_classes(attrs):
    m = re.search(r'class\s*=\s*"(.*?)"', attrs, re.I|re.S)
    return m.group(1).strip() if m else ""

def make_link(classes):
    return '<a href="{{ url_for(\'hexes_gallery\') }}"' + (f' class="{classes}"' if classes else "") + '>Hexes</a>'

def inject_navbar_link():
    if not os.path.isdir(TEMPLATES_DIR):
        log(f"[WARN] templates dir not found at {TEMPLATES_DIR}. Skipping navbar patch."); return
    candidates = []
    for root, _, files in os.walk(TEMPLATES_DIR):
        for fn in files:
            if fn.endswith(".html"):
                path = os.path.join(root, fn)
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    html = f.read()
                if "Potions" in html or "Races" in html or "Classes" in html:
                    candidates.append((path, html))
    inserted = False
    for path, html in candidates:
        if "hexes_gallery" in html and re.search(r'>\s*Hexes\s*<', html, re.I):
            continue
        m = re.search(r'<a(?P<attrs>[^>]+)>\s*Classes\s*</a>', html, re.I)
        if not m:
            m = re.search(r'<a(?P<attrs>[^>]+)>\s*Races\s*</a>', html, re.I)
        if m:
            classes = clone_classes(m.group('attrs'))
            new_link = make_link(classes)
            new_html = html[:m.end()] + "\n        " + new_link + html[m.end():]
            with open(path, "w", encoding="utf-8") as f: f.write(new_html)
            log(f"[OK] Inserted Hexes in navbar of {os.path.relpath(path, PROJECT_ROOT)}")
            inserted = True
            break
        if "</nav>" in html:
            new_html = html.replace("</nav>", "  " + make_link("") + "\n</nav>")
            with open(path, "w", encoding="utf-8") as f: f.write(new_html)
            log(f"[OK] Inserted Hexes before </nav> in {os.path.relpath(path, PROJECT_ROOT)}")
            inserted = True
            break
    if not inserted:
        log("[WARN] Could not find navbar to patch. Add link manually using layout_nav_snippet.txt.")

def inject_data_chip():
    if not os.path.isdir(TEMPLATES_DIR):
        log(f"[WARN] templates dir not found at {TEMPLATES_DIR}. Skipping data chip patch."); return
    inserted = False
    for root, _, files in os.walk(TEMPLATES_DIR):
        for fn in files:
            if not fn.endswith(".html"): continue
            path = os.path.join(root, fn)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
            if "hexes_gallery" in html and re.search(r'>\s*Hexes\s*<', html, re.I):
                continue
            m = re.search(r'<a(?P<attrs>[^>]+)>\s*Items\s*</a>', html, re.I)
            if not m:
                m = re.search(r'<a(?P<attrs>[^>]+)>\s*Gear\s*</a>', html, re.I)
            if m:
                classes = clone_classes(m.group('attrs'))
                new_link = make_link(classes)
                new_html = html[:m.end()] + "\n        " + new_link + html[m.end():]
                with open(path, "w", encoding="utf-8") as f: f.write(new_html)
                log(f"[OK] Inserted Hexes chip in {os.path.relpath(path, PROJECT_ROOT)}")
                inserted = True
                break
    if not inserted:
        log("[WARN] Could not find Data chip area (Items/Gear). Use data_chip_snippet.html to add manually.")

if __name__ == "__main__":
    ensure_hex_dir()
    ensure_hexes_template()
    ensure_route()
    inject_navbar_link()
    inject_data_chip()
    log("\nDone. Drop images into static/hexes/ and visit /hexes")
