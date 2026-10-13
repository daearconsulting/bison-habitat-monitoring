"""Remove Jupyter's unused AMD bootstrap (conflicts with Quarto's UMD scripts).

Outputs use standalone Plotly HTML, Folium iframes and Quarto OJS, none of
which requires the notebook's global RequireJS loader.
"""
from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
for page in (root / "_site").rglob("*.html"):
    text=page.read_text(encoding="utf-8")
    text=re.sub(r'<script[^>]+src="https://cdn\.jsdelivr\.net/npm/requirejs@[^" ]+/require\.min\.js"[^>]*></script>', '', text)
    text=re.sub(r"<script[^>]*>define\('jquery', \[\],function\(\) \{return window\.jQuery;\}\)</script>", '', text)
    page.write_text(text,encoding="utf-8")
