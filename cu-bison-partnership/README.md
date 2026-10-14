# Buffalo on the Front Range

A short website for CU Boulder leaders and potential partners explaining why a research university has a role in buffalo restoration, what Colorado already does, three partnership models, and a first-look map of large open grasslands near Boulder. This is intended as a discussion resource.

**Prepared by:** Lilly Jones, PhD

## What is in this folder

| Path | What it is |
|---|---|
| `*.qmd` | The website pages. Most are plain text; edit the words directly. |
| `site.yaml` | Settings: screening region, grassland rules, and map points. |
| `sitekit/` | Python helpers. `fetch.py` downloads data and finds grassland blocks; `show.py` draws maps; `demo.py` makes fake preview data. |
| `scripts/build_data.py` | Downloads the public data and writes small files to `data/processed/`. |
| `scripts/check_data.py` | Stops a publish if the data is missing or is preview data. |
| `.github/workflows/publish.yml` | Builds and publishes the site to GitHub Pages automatically. |

## Data and facts

- **Map:** Rangeland Analysis Platform v3 vegetation cover (latest year available). Grassland blocks are contiguous areas meeting the rules in `site.yaml` (perennial grass and forb cover, tree cover, bare ground, minimum size). Land ownership is deliberately not included.
- **Herd facts:** cited on the Sources page (CSU, Denverite, WWF, CU's CNAIS site). Re-check numbers before a meeting; transfer totals grow every year.
- **Herd locations** in `site.yaml` are approximate, for orientation only.

## Publish it on GitHub (one time, about 15 minutes)

1. **Create an empty repository** on GitHub. On a free account it must be public for Pages to work, and the website itself is always public.
2. **Upload this folder's contents**.
3. **Turn on Pages:** repo **Settings - Pages - Build and deployment - Source: GitHub Actions**.
4. **Run the first build:*  * **Actions - Build and publish site - Run workflow**. It takes about 5 to 10 minutes.
5. The site address appears on the run's summary page.

The data refreshes monthly; edits pushed to `main` republish in a few minutes.

## Preview it on your own computer

Install [Quarto](https://quarto.org/docs/get-started/) and [Miniforge](https://conda-forge.org/download/), then from this folder:

```powershell
conda env create -f environment.yml     # one time
conda activate range-sites

python scripts/build_data.py            # real data (needs internet)
# or: python scripts/build_data.py --demo   (fake data, layout check only)

quarto preview
```

The two sites share one environment, so you only need to create it once.

## Tuning the grassland map

In `site.yaml`, under `grassland`:

- Raise `min_perennial_cover_pct` for a stricter perennial-cover threshold.
- Raise `min_block_acres` to show only very large areas.
- If the eastern plains merge into one enormous block, that is real (large connected rangeland). The table on the page still lists blocks by size and distance.

Then rebuild the data.

## Data safeguards and analytical extent

Failed refreshes leave the previous processed directory intact. Partial rebuilds require an existing validated real build; they cannot convert preview data to real data. Publication requires every configured dataset, its listed files, valid observations, and current retrieval dates. Run `python -m unittest discover -s tests -v` for regression checks.

The fixed 2024 Annual NLCD mask includes classes 52 (shrub/scrub) and 71 (grassland/herbaceous). It excludes mapped cropland, hay/pasture, developed land, forest, water and wetlands. This is a conservative vegetation screen, not proof of native species, irrigation status or available grazing land. Historical RAP summaries describe the **same fixed-vintage eligible footprint**, not historical land-use change. The mask is sampled with nearest-neighbor resampling onto the analysis grid. `landcover.raster` can be a local GeoTIFF or a remote COG; its default is a NatCap mirror of the USGS/MRLC product. Update the year and source URL together if replacing it.

## Printing and PDF

Use the page's Print/Save PDF button or your browser's Print command. Print styling replaces interactive maps and charts with static figures; the herd calculator includes a static starting-assumptions table. Choose “Save as PDF” in the print dialog. This is a browser-generated PDF rather than a separate LaTeX build.

For the tested direct package versions, use `python -m pip install -r requirements.txt -c constraints.txt` after activating the environment. The workflow pins Quarto 1.8.27. Transitive dependencies are still resolved by pip; this is not a fully locked environment.
