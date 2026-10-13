"""sitekit: data building and figure helpers for this Quarto site.

Two halves:
  * fetch.py / demo.py  -> run once (by scripts/build_data.py) to write data/processed/
  * show.py             -> used by the .qmd pages; only ever READS data/processed/

Keeping these separate means the website renders quickly and never depends on
an outside data service being up at the moment someone opens the page.
"""
