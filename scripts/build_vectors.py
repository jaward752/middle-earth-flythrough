#!/usr/bin/env python3
"""Step 6: all 26 shapefiles -> lon/lat GeoJSON -> tiles/vectors.pmtiles.

- Every layer is re-anchored with the -s_srs override from CLAUDE.md (the same
  translation the raster got), then inverse-Mercator'd to EPSG:4326.
- The DEM-derived coastline (geojson/Coastline.geojson, built once, see CLAUDE.md)
  is included as layer `coastline`.
- Derived label layers: `towns` gets a `rank` (1 capital .. 4 village) from Type;
  `realm_labels` and `mountain_labels` are one representative point per polygon
  (ST_PointOnSurface, computed in the source CRS before reprojection).
- tippecanoe runs with -r1 so points are never thinned at low zoom (73 towns is
  nothing), and --drop-densest-as-needed only kicks in for oversized tiles.
"""
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

SRC = "Vector_Shapefiles"
OUT = "geojson"
S_SRS = "+proj=merc +a=6378137 +b=6378137 +x_0=3703364.2196 +y_0=2265303.6458 +units=m +no_defs"
LAYERS = ["Bays", "Bridges", "Buildings", "Cave_entrances", "Doors_Gates", "Falls", "Fields",
          "Fords", "Forests", "Fortresses", "Frodo_Route", "Graves_Tombs", "Harbors", "Hills",
          "Islands", "Lakes", "Mountains", "Mountains_of_Moria", "Place_Boundaries", "Realms",
          "Rivers", "Roads", "Swamps", "Towns", "Valleys", "Walls"]
KEEP = ["Name", "Type", "Range", "Realm", "Inhabitant", "River", "English", "Sindarin"]


def rank(t):
    t = (t or "").lower()
    if "capital" in t or "city state" in t or t == "realm":
        return 1
    if "city" in t or "seaport" in t:
        return 2
    if "town" in t or "harbor" in t or "fortress" in t:
        return 3
    return 4


def convert(name, sql=None, out=None):
    out = os.path.join(OUT, (out or name) + ".geojson")
    cmd = ["ogr2ogr", "-f", "GeoJSON", "-t_srs", "EPSG:4326", "-s_srs", S_SRS, "-lco", "COORDINATE_PRECISION=6"]
    if sql:
        cmd += ["-dialect", "sqlite", "-sql", sql]
    cmd += [out, os.path.join(SRC, name + ".shp")]
    subprocess.run(cmd, check=True, capture_output=True)
    g = json.load(open(out))
    for f in g["features"]:
        p = f["properties"]
        f["properties"] = {k: v for k, v in p.items() if k in KEEP and v not in (None, "")}
        if name == "Towns":
            f["properties"]["rank"] = rank(p.get("Type"))
    json.dump(g, open(out, "w"), ensure_ascii=False)
    return out, len(g["features"])


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [(n, None, None) for n in LAYERS]
    jobs += [("Realms", "SELECT Name, ST_PointOnSurface(geometry) AS geometry FROM Realms", "realm_labels"),
             ("Mountains", "SELECT Name, Type, Range, ST_PointOnSurface(geometry) AS geometry FROM Mountains", "mountain_labels")]
    with ThreadPoolExecutor(8) as ex:
        for out, n in ex.map(lambda j: convert(*j), jobs):
            print(f"{n:5d}  {out}")

    cmd = ["tippecanoe", "-q", "-f", "-o", "tiles/vectors.pmtiles", "-Z0", "-z12", "-r1",
           "--drop-densest-as-needed", "--detect-shared-borders",
           "-L", f"coastline:{OUT}/Coastline.geojson"]
    for n in LAYERS:
        cmd += ["-L", f"{n.lower()}:{OUT}/{n}.geojson"]
    cmd += ["-L", f"realm_labels:{OUT}/realm_labels.geojson", "-L", f"mountain_labels:{OUT}/mountain_labels.geojson"]
    subprocess.run(cmd, check=True)
    print("wrote tiles/vectors.pmtiles")


if __name__ == "__main__":
    main()
