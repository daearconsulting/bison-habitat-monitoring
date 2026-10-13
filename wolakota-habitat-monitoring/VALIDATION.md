# Implementation and validation

Updated both original projects in `C:\Users\gekek\Documents\bison-habitat-monitoring` on October 13, 2026.

Implemented:

- Strict publication validation: mixed preview/real provenance, missing datasets/files, incomplete file inventories, invalid geometries, invalid observations, and stale retrieval dates block publication.
- Transactional builds: fetch into staging, validate, then promote. Failed refreshes preserve the previous processed directory. Partial builds cannot convert demo data to real data.
- Correct USGS waterbody layer (9), geometry/FCode checks, server-side perennial-stream filtering, smaller query pages, and explicit errors for undefined distance surfaces.
- Fixed raster bounds and actual pixel spacing; RAP source CRS validation.
- Fixed-vintage 2024 Annual NLCD grassland/shrubland mask for both analyses, excluding mapped crops, hay/pasture and development. Added eligible acreage/coverage reporting and methodological explanations. The mask does not identify native species or irrigation status.
- Complete RAP history and 30-year baseline requirements, minimum spatial coverage, latest-map checks, drought CSV/schema/percentage/date validation, and explicit equal-county-average labeling.
- Missing-data homepage/calculator handling and null-year-safe fire charts.
- CU grassland polygon repair and coordinate quantization, verified through a full real build and GeoJSON round-trip validation.
- Browser printing with static chart/map replacements and a calculator assumptions/results table; Print / Save PDF buttons on all pages.
- Removal of an unused notebook AMD loader that caused browser JavaScript errors.
- Regression checks in each site, Quarto 1.8.27 pin, tested direct Python dependency constraints, and workflow validation/rendering before saving refreshed data.

Verification:

- 16 regression checks passed across the two projects (9 Wolakota, 7 CU).
- Both complete Quarto sites rendered with preview data (9 and 7 pages).
- CU completed a full real-data build using RAP 2025 and the 2024 land-cover mask, passed the publication gate, and rendered all seven pages with real data. The screen produced 15 vegetation blocks; they remain illustrative vegetation screens rather than validated herd sites.
- Real RAP cover/biomass and land-cover samples were read successfully. Drought Monitor returned the expected CSV with exclusive categories. Census, the complete 1986–2025 RAP series, drought, and fire processing completed in the Wolakota real build.
- Wolakota's full build failed at USGS hydrography with HTTP 504. A smaller filtered water query also returned 504. The failed build did not replace its preview dataset. Wolakota therefore remains a visibly labeled preview and its publication gate rejects it.
- Browser checks covered the herd calculator, forage, water, and CU landscape pages. The repaired outputs had no page JavaScript or Observable errors. Three calculator sliders were present; print maps/charts were available. A separate missing-data calculator render also succeeded.

Limits and maintenance:

- GitHub Actions deployment was not run; no repositories or sites were published.
- The Python constraints pin tested direct dependencies, not the entire transitive dependency graph.
- The land-cover raster defaults to a verified NatCap mirror of the MRLC/USGS 2024 product; the path is configurable. It is a fixed footprint for historical comparisons, not a reconstruction of yearly land-use change.
- PDF output uses the browser print dialog. Static maps omit external basemap tiles and show the thematic layers. Calculator print results use the documented starting assumptions rather than transient slider values.
- Wolakota needs a successful full real build once the USGS service responds. From its directory, run `python scripts/build_data.py`, then `python scripts/check_data.py`, then `quarto render`. Keep the preview site separate from any public publication until that gate passes.

