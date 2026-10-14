from __future__ import annotations

"""Figure and map helpers for the website pages.

Pages call these with a line or two each, so the .qmd files stay readable as
plain-language documents. Nothing here downloads anything; it only reads
data/processed/ (built by scripts/build_data.py).
"""

import base64
import io

import folium
import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import rasterio

from .config import PROCESSED, read_manifest, has_demo

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Shared look

INK = "#2b2a26"
MUTED = "#6b665c"
GRID = "#e6e1d6"
GRASS = "#4f7a3a"
EARTH = "#9a6b3c"
WATER = "#2f6d8f"
FIRE = "#c4532b"
DROUGHT = {"d0": "#f5e663", "d1": "#f2c26b", "d2": "#e8913a", "d3": "#c8432b", "d4": "#7a1f14"}
DROUGHT_LABEL = {"d0": "Abnormally dry", "d1": "Moderate drought", "d2": "Severe drought",
                 "d3": "Extreme drought", "d4": "Exceptional drought"}

pio.templates["site"] = go.layout.Template(layout=go.Layout(
    font=dict(family="Source Sans 3, Helvetica, Arial, sans-serif", size=15, color=INK),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, ticks="", automargin=True),
    yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, ticks="", automargin=True,
               title=dict(standoff=12)),
    margin=dict(l=10, r=10, t=40, b=10), hoverlabel=dict(font_size=14),
    legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"),
))
pio.templates.default = "site"
CHART_CONFIG = {"displayModeBar": False, "responsive": True}

MANIFEST = read_manifest()
OUTLINE_LABEL = "Example region outline"


# Status messages (printed with `#| output: asis`)

def preview_banner() -> str:
    if has_demo(MANIFEST):
        return ("::: {.callout-warning appearance=\"simple\"}\n"
                "**Preview data.** The maps and charts on this page use made-up numbers so the layout "
                "can be checked. Rebuild the data before sharing this site.\n:::\n")
    return ""


def available(key: str) -> bool:
    entry = MANIFEST.get("datasets", {}).get(key, {})
    return entry.get("status") in {"ok", "demo"} and bool(entry.get("files")) and all((PROCESSED / f).is_file() for f in entry["files"])


def missing_note(what: str) -> str:
    return (f"::: {{.callout-note appearance=\"simple\"}}\nThe {what} data could not be retrieved "
            "the last time this site was built. It will appear the next time the data service "
            "responds.\n:::\n")


def latest_year() -> int | None:
    return MANIFEST.get("latest_rap_year")


# Loaders

def area() -> gpd.GeoDataFrame:
    return gpd.read_file(PROCESSED/"area.geojson")


def area_acres() -> float:
    return float(area()["acres"].sum())


def rap_series() -> pd.DataFrame:
    return pd.read_csv(PROCESSED/"rap_annual.csv")


def drought_weekly() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED/"drought_weekly.csv", parse_dates=["date"])
    # Average the counties so the chart shows one region-wide picture.
    cols = ["none", "d0", "d1", "d2", "d3", "d4"]
    return df.groupby("date", as_index=False)[cols].mean()


def raster_stats(name: str) -> dict:
    with rasterio.open(PROCESSED/name) as src:
        a = src.read(1)
    v = a[np.isfinite(a)]
    return {"mean": float(v.mean()), "p10": float(np.percentile(v, 10)),
            "p90": float(np.percentile(v, 90)), "values": v}


# Maps

def _png(arr: np.ndarray, cmap: str, vmin: float, vmax: float) -> str:
    rgba = matplotlib.colormaps[cmap](np.clip((arr - vmin) / (vmax - vmin), 0, 1))
    rgba[~np.isfinite(arr)] = (0, 0, 0, 0)
    buf = io.BytesIO()
    matplotlib.pyplot.imsave(buf, rgba, format="png")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def base_map() -> folium.Map:
    a = area()
    minx, miny, maxx, maxy = a.total_bounds
    m = folium.Map(tiles=None, control_scale=True, zoom_snap=0.25, scrollWheelZoom=False)
    folium.TileLayer(
        tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="OpenStreetMap", control=True, max_zoom=19,
    ).add_to(m)
    folium.FeatureGroup(name="Data only (no basemap)", overlay=False, show=False).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    return m


def add_outline(m: folium.Map) -> None:
    folium.GeoJson(area().__geo_interface__, name=OUTLINE_LABEL,
                   style_function=lambda _: {"color": INK, "weight": 2, "fill": False, "dashArray": "6 4"}
                   ).add_to(m)


def raster_layer(m: folium.Map, name: str, label: str, cmap: str, vmin: float, vmax: float,
                 colors: list[str], legend: str, opacity: float = 0.85, show: bool = True) -> None:
    with rasterio.open(PROCESSED / name) as src:
        arr = src.read(1)
        b = src.bounds
    folium.raster_layers.ImageOverlay(_png(arr, cmap, vmin, vmax), bounds=[[b.bottom, b.left], [b.top, b.right]],
                                      name=label, opacity=opacity, show=show, interactive=False).add_to(m)
    # Legends are drawn under the map (not on it) so they never cover the land or each other.
    _legends(m).append({"kind": "ramp", "label": legend, "colors": colors, "vmin": vmin, "vmax": vmax,
                        "hidden": not show})


def _legends(m) -> list:
    if not hasattr(m, "_site_legends"):
        m._site_legends = []
    return m._site_legends


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1 or v == 0 else f"{v:.1f}"


def legend_html(items: list[dict]) -> str:
    parts = []
    for it in items:
        if it["kind"] == "ramp":
            grad = ", ".join(it["colors"])
            note = " <span class='lg-note'>(turn on with the layer button)</span>" if it["hidden"] else ""
            parts.append(
                f"<div class='lg-item'><div class='lg-label'>{it['label']}{note}</div>"
                f"<div class='lg-ramp' style='background: linear-gradient(to right, {grad});'></div>"
                f"<div class='lg-ends'><span>{_fmt(it['vmin'])}</span><span>{_fmt(it['vmax'])}+</span></div></div>")
        else:
            style = (f"background:{it['color']};opacity:.6;border:1px solid {it['color']};" if it["fill"]
                     else f"height:3px;margin-top:9px;background:{it['color']};")
            parts.append(f"<div class='lg-item lg-swatch'><span style='{style}'></span>{it['label']}</div>")
    return "<div class='map-legend'>" + "".join(parts) + "</div>"


class MapBlock:
    """A map plus its legend, displayed together on the page."""

    def __init__(self, fig: folium.Figure, legends: list[dict], static_html: str):
        self.fig, self.legends, self.static_html = fig, legends, static_html

    def _repr_html_(self) -> str:
        return '<div class="interactive-figure">' + self.fig._repr_html_() + "</div>" + self.static_html + legend_html(self.legends)


def finish(m: folium.Map, height: int = 520) -> MapBlock:
    """Add the outline and layer switcher, size the map, and attach its legend."""
    add_outline(m)
    folium.LayerControl(collapsed=True).add_to(m)
    fig = folium.Figure(width="100%", height=height)
    m.add_to(fig)
    return MapBlock(fig, _legends(m) + [{"kind": "swatch", "label": OUTLINE_LABEL,
                                          "color": INK, "fill": False}], static_map(m))


def vector_layer(m: folium.Map, name: str, label: str, color: str, weight: float = 1.5,
                 fill: bool = False, tooltip: list[str] | None = None, aliases: list[str] | None = None,
                 show: bool = True) -> None:
    gdf = gpd.read_file(PROCESSED / name)
    if gdf.empty:
        return
    kw = {}
    if tooltip:
        kw["tooltip"] = folium.GeoJsonTooltip(fields=tooltip, aliases=aliases or tooltip, localize=True)
    _legends(m).append({"kind": "swatch", "label": label, "color": color, "fill": fill})
    folium.GeoJson(gdf.__geo_interface__, name=label, show=show,
                   style_function=lambda _: {"color": color, "weight": weight, "fill": fill,
                                             "fillColor": color, "fillOpacity": 0.35 if fill else 0},
                   **kw).add_to(m)


# Charts

def show(fig: go.Figure, height: int = 360) -> None:
    fig.update_layout(height=height)
    from IPython.display import display, HTML
    display(HTML('<div class="interactive-figure">' + fig.to_html(full_html=False, include_plotlyjs="cdn", config=CHART_CONFIG) + '</div>' + static_chart(fig)))


def dry_years(series: pd.DataFrame, q: float = 0.2) -> list[int]:
    """Years in the driest fifth by total forage (used to shade charts)."""
    cut = series["forage_total_lbs_ac"].quantile(q)
    return series.loc[series["forage_total_lbs_ac"] <= cut, "year"].astype(int).tolist()


def shade_years(fig: go.Figure, years: list[int], label: str = "Low-forage year") -> None:
    for i, y in enumerate(years):
        fig.add_vrect(x0=y - 0.5, x1=y + 0.5, fillcolor=EARTH, opacity=0.10, line_width=0,
                      annotation_text=label if i == 0 else None, annotation_position="top left",
                      annotation_font_color=MUTED, annotation_font_size=12)


def _static_image(fig, alt):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    src = base64.b64encode(buf.getvalue()).decode()
    return f'<img class="print-figure" alt="{alt}" src="data:image/png;base64,{src}">'


def static_map(m):
    """Printable thematic map; no external basemap or tile downloads."""
    from shapely.geometry import shape
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.set_facecolor("#f6f3ec")
    for child in m._children.values():
        if isinstance(child, folium.raster_layers.ImageOverlay) and child.show:
            payload = child.url.split(",", 1)[1]
            arr = plt.imread(io.BytesIO(base64.b64decode(payload)))
            (south, west), (north, east) = child.bounds
            ax.imshow(arr, extent=(west, east, south, north), origin="upper", aspect="auto", alpha=child.options.get("opacity", 1.0))
        elif isinstance(child, folium.GeoJson) and child.show:
            features = child.data.get("features", [])
            if features:
                frame = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
                style = child.style_function(features[0]) if child.style_function else {}
                frame.plot(ax=ax, facecolor=style.get("fillColor", "none") if style.get("fill") else "none",
                           edgecolor=style.get("color", INK), linewidth=0.8, alpha=0.7)
        elif isinstance(child, folium.FeatureGroup):
            for marker in child._children.values():
                if isinstance(marker, folium.CircleMarker):
                    lat, lon = marker.location
                    ax.scatter([lon], [lat], color=marker.options.get("fillColor", EARTH), edgecolor=INK, s=35)
    minx, miny, maxx, maxy = area().total_bounds
    ax.set(xlim=(minx,maxx), ylim=(miny,maxy), xlabel="Longitude", ylabel="Latitude")
    ax.set_aspect(1 / np.cos(np.deg2rad((miny+maxy)/2)))
    ax.set_title("Public-data illustration — see source and limitations on this page")
    return _static_image(fig, "Printable map of the visible thematic layers; background tiles omitted")


def static_chart(chart):
    fig, ax = plt.subplots(figsize=(9, 3.8))
    stacked = [t for t in chart.data if getattr(t, "stackgroup", None)]
    if stacked:
        ax.stackplot(list(stacked[0].x), *[list(t.y) for t in stacked],
                     labels=[t.name for t in stacked], colors=[t.fillcolor for t in stacked])
    else:
        bottom = None
        for trace in chart.data:
            x, y = list(trace.x), np.asarray(trace.y, dtype=float)
            if trace.type == "bar":
                color = trace.marker.color
                if chart.layout.barmode == "stack":
                    if bottom is None: bottom = np.zeros_like(y)
                    ax.bar(x, y, bottom=bottom, label=trace.name, color=color)
                    bottom += y
                else:
                    ax.bar(x, y, label=trace.name, color=color)
            else:
                ax.plot(x, y, label=trace.name, color=trace.line.color or None)
    ax.set_ylabel(chart.layout.yaxis.title.text or "")
    ax.set_xlabel(chart.layout.xaxis.title.text or "")
    if chart.layout.yaxis.range:
        ax.set_ylim(*chart.layout.yaxis.range)
    if len(chart.data) > 1:
        ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    return _static_image(fig, "Printable chart with the same observations as the interactive chart")



def fire_year_totals(frame):
    clean = frame.dropna(subset=["year"]).copy()
    clean["year"] = clean["year"].astype(int)
    return clean.groupby("year")["acres_in_area"].sum()
