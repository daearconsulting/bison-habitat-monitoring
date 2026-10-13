# Watching the Range

A small website that shows what buffalo habitat monitoring *could* look like, using only free, national, public data, for discussion with the Wolakota team and others. It is an illustration, not an assessment of the Wolakota Buffalo Range, and it makes no decisions or recommendations for Wolakota.

**Audience:** decision makers who do not code. They only ever see the published website. Everything below is for whoever maintains it.

**Author:** Lilly Jones, PhD, Daear Consulting, LLC

## What is in this folder

| Path | What it is |
|---|---|
| `*.qmd` | The website pages, written as plain text with small code blocks (hidden on the site). Edit the words here. |
| `site.yaml` | The one settings file: area, counties, and example values. Change the area here, never in code. |
| `sitekit/` | Python helpers. `fetch.py` downloads data; `show.py` draws maps and charts; `demo.py` makes fake preview data. |
| `scripts/build_data.py` | Downloads the public data and writes small files to `data/processed/`. |
| `scripts/check_data.py` | Stops a publish if the data is missing or is preview data. |
| `data/processed/` | The processed data the pages read. Committed to the repo so the site can be rebuilt quickly. |
| `.github/workflows/publish.yml` | Builds and publishes the site to GitHub Pages automatically. |

## Data sources

| Page | Data | Source |
|---|---|---|
| How much grass grew, Forage and herd size, Invasive annual grasses | Yearly plant cover and forage, 1986 to present | Rangeland Analysis Platform v3 |
| Drought | Weekly drought category by county | U.S. Drought Monitor data services |
| Water across the land | Year-round streams, ponds, reservoirs | USGS NHDPlus High Resolution |
| Fire history | Past fire perimeters | NIFC InterAgency Fire Perimeter History |
| All maps | Example region boundary | U.S. Census TIGER/Line AIANNH 2023 |

No Tribal, herd, or ranch data is used or stored anywhere in this project.

## Publish it on GitHub (one time, about 15 minutes)

1. **Create an empty repository** on GitHub (for example `wolakota-habitat-monitoring`). On a free GitHub account, the repository must be public for Pages to work, and the published website is always public.
2. **Upload this folder's contents** to the repository (drag and drop on the repo page works, or use GitHub Desktop). Make sure the hidden `.github` folder is included.
3. **Turn on Pages:** repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. **Run the first build:** repo **Actions → Build and publish site → Run workflow** (leave "Download fresh public data" checked). The first run takes roughly 15 to 40 minutes, mostly downloading 40 years of vegetation data.
5. When it finishes, the site address appears on the run's summary page (usually `https://<your-account>.github.io/<repo-name>/`).

After that, the site refreshes itself every Friday. Any edit you push to `main` republishes in a few minutes using the data already saved.

> The very first push will show a failed run, because no real data exists yet. That is expected; step 4 fixes it.

## Preview it on your own computer

These commands use PowerShell on Windows; they are the same in a Mac or Linux terminal. Install [Quarto](https://quarto.org/docs/get-started/) and [Miniforge](https://conda-forge.org/download/) first.

```powershell
# 1. From this folder, create and activate the environment (one time)
conda env create -f environment.yml
conda activate range-sites

# 2a. Real data (needs internet; 15-40 minutes the first time)
python scripts/build_data.py

# 2b. OR fake preview data, just to look at the layout (seconds; pages show a "Preview data" banner)
python scripts/build_data.py --demo

# 3. Open a live preview in your browser; it updates as you edit .qmd files
quarto preview
```

Rebuild only part of the data: `python scripts/build_data.py --only drought water`.

## Change the area

Edit `site.yaml`:

- To use a different Census reservation area, change `census_aiannh_name` and `clip_bbox` (or set `clip_bbox: null`).
- If the Wolakota team ever chooses to share a range boundary, set `boundary_file` to that file. **Keep that boundary out of a public repository unless the team explicitly approves.**
- Update `drought_counties` and `drought_area_label` to match.

Then rebuild the data.

## Things to verify before sharing widely

- **Live service validation: see VALIDATION.md.** The repaired code has been exercised with live samples; see VALIDATION.md for the full-build status and remaining limitations.
- **Service details.** The RAP file naming (`.../rap-vegetation-biomass/v3/vegetation-biomass-v3-<year>.tif`) follows the RAP team's documented pattern for cover files; the biomass path and both product band layouts have now been checked against live samples. The Drought Monitor CSV column names and the NIFC fire service address are handled flexibly, but confirm them on the first run.
- **Review by the right people.** Before this circulates beyond James Rattling Leaf, consider letting someone connected to Wolakota see it first, since it describes their region.
- **License.** No license file is included yet. Add one you are comfortable with (for example Apache 2.0 for the code).


## Data safeguards and analytical extent

Builds now stage all outputs and promote them only after validation. Failed refreshes leave the previous processed directory intact. Partial rebuilds require an existing validated real build; they cannot convert preview data to real data. Publication requires every configured dataset, its listed files, valid observations, and current retrieval dates. Run `python -m unittest discover -s tests -v` for regression checks.

The fixed 2024 Annual NLCD mask includes classes 52 (shrub/scrub) and 71 (grassland/herbaceous). It excludes mapped cropland, hay/pasture, developed land, forest, water and wetlands. This is a conservative vegetation screen, not proof of native species, irrigation status or available grazing land. Historical RAP summaries describe the **same fixed-vintage eligible footprint**, not historical land-use change. The mask is sampled with nearest-neighbor resampling onto the analysis grid. `landcover.raster` can be a local GeoTIFF or a remote COG; its default is a NatCap mirror of the USGS/MRLC product. Update the year and source URL together if replacing it.

## Printing and PDF

Use the page's Print / Save PDF button or your browser's Print command. Print styling replaces interactive maps and charts with static figures; the herd calculator includes a static starting-assumptions table. Choose “Save as PDF” in the print dialog. This is a browser-generated PDF rather than a separate LaTeX build.

For the tested direct package versions, use `python -m pip install -r requirements.txt -c constraints.txt` after activating the environment. The workflow pins Quarto 1.8.27. Transitive dependencies are still resolved by pip; this is not a fully locked environment.
