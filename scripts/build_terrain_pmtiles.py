#!/usr/bin/env python3
"""Build Terrain-RGB PMTiles (512 px tiles) from a float EPSG:3857 DEM.

Replaces `rio rgbify` + `rio pmtiles`, which are not installable here (no venv).

Why not encode once and let the tiler resample: Terrain-RGB packs elevation into
three bytes, so averaging or interpolating the bytes produces garbage where a
channel wraps. Every zoom must be resampled as floats first and encoded after.

Per zoom, per strip of tile rows (strips run in parallel):
  1. gdalwarp -of VRT   float DEM -> tile-aligned grid at that zoom (average from
                        the DEM's overviews; area outside the DEM becomes 0 m)
  2. expression VRT     float -> Mapbox Terrain-RGB, base -10000, interval 0.1
  3. gdal_translate     -> MBTiles, PNG, BLOCKSIZE=512, ZOOM_LEVEL=z
Then merge all strip MBTiles with sqlite and run `pmtiles convert`.
"""
import argparse, math, os, shutil, sqlite3, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from osgeo import gdal

gdal.UseExceptions()
WORLD = 40075016.68557849          # EPSG:3857 extent in metres
ORIGIN = -WORLD / 2
TILE_PX = 512
R_EARTH = 6378137.0

# Mapbox Terrain-RGB: h = -10000 + (R*65536 + G*256 + B) * 0.1
# muparser has no floor(), so floor(x) for x >= 0 is rint(x - 0.5 + eps).
V = "rint((h+10000)*10)"
FLOOR = lambda x: f"rint({x} - 0.5 + 1e-7)"
EXPR = [
    FLOOR(f"{V}/65536"),
    f"{FLOOR(f'{V}/256')} - 256*{FLOOR(f'{V}/65536')}",
    f"{V} - 256*{FLOOR(f'{V}/256')}",
]


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def rgb_vrt(src_vrt, out_vrt):
    ds = gdal.Open(src_vrt)
    gt = ds.GetGeoTransform()
    bands = "\n".join(
        f'  <VRTRasterBand dataType="Byte" band="{i+1}" subClass="VRTDerivedRasterBand">\n'
        f'    <PixelFunctionType>expression</PixelFunctionType>\n'
        f'    <PixelFunctionArguments expression="{e}" />\n'
        f'    <SimpleSource name="h"><SourceFilename relativeToVRT="0">{src_vrt}</SourceFilename>'
        f'<SourceBand>1</SourceBand></SimpleSource>\n'
        f'  </VRTRasterBand>' for i, e in enumerate(EXPR))
    with open(out_vrt, "w") as f:
        f.write(f'<VRTDataset rasterXSize="{ds.RasterXSize}" rasterYSize="{ds.RasterYSize}">\n'
                f'  <SRS>{ds.GetProjection()}</SRS>\n'
                f'  <GeoTransform>{", ".join(repr(v) for v in gt)}</GeoTransform>\n'
                f'{bands}\n</VRTDataset>\n')


def strip_job(args):
    src, z, tx0, tx1, ty0, ty1, work = args
    tile_m = WORLD / 2 ** z
    res = tile_m / TILE_PX
    te = (ORIGIN + tx0 * tile_m, WORLD / 2 - ty1 * tile_m,
          ORIGIN + tx1 * tile_m, WORLD / 2 - ty0 * tile_m)
    base = os.path.join(work, f"z{z:02d}_r{ty0:05d}")
    f_vrt, rgb, mb = base + ".vrt", base + "_rgb.vrt", base + ".mbtiles"
    run(["gdalwarp", "-q", "-overwrite", "-of", "VRT", "-r", "near" if z == 12 else "average",
         "-tr", repr(res), repr(res), "-te", *map(repr, te), src, f_vrt])
    rgb_vrt(f_vrt, rgb)
    if os.path.exists(mb):
        os.remove(mb)
    run(["gdal_translate", "-q", "-of", "MBTiles", "-co", f"BLOCKSIZE={TILE_PX}",
         "-co", "TILE_FORMAT=PNG", "-co", "RESAMPLING=NEAREST", "-co", f"ZOOM_LEVEL={z}",
         "-co", "WRITE_MINMAXZOOM=NO", rgb, mb])
    return mb


def merge(strips, out, bounds_ll, minz, maxz):
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript("""
        CREATE TABLE metadata (name TEXT, value TEXT);
        CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);
        CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);""")
    for i, s in enumerate(strips):
        db.execute(f"ATTACH DATABASE ? AS s{i}", (s,))
        db.execute(f"INSERT OR REPLACE INTO tiles SELECT zoom_level, tile_column, tile_row, tile_data FROM s{i}.tiles")
        db.commit()
        db.execute(f"DETACH DATABASE s{i}")
    w, s_, e, n = bounds_ll
    meta = {"name": "Middle-earth Terrain-RGB", "format": "png", "type": "baselayer", "version": "1",
            "description": "Mapbox Terrain-RGB (base -10000, interval 0.1), 512px tiles, "
                           "W&M CGA 'GIS & Middle Earth' DEM, CC BY-NC-SA 4.0",
            "minzoom": str(minz), "maxzoom": str(maxz),
            "bounds": f"{w:.6f},{s_:.6f},{e:.6f},{n:.6f}",
            "center": f"{(w+e)/2:.6f},{(s_+n)/2:.6f},{max(minz, 4)}"}
    db.executemany("INSERT INTO metadata VALUES (?,?)", meta.items())
    db.commit()
    db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dem"); p.add_argument("out_pmtiles")
    p.add_argument("--zooms", default="0-12"); p.add_argument("--workers", type=int, default=12)
    p.add_argument("--work", default="work_terrain"); p.add_argument("--strip-px", type=float, default=600e6)
    p.add_argument("--keep-work", action="store_true")
    a = p.parse_args()
    minz, maxz = map(int, a.zooms.split("-"))
    os.makedirs(a.work, exist_ok=True)

    ds = gdal.Open(a.dem)
    gt = ds.GetGeoTransform()
    minx, maxy = gt[0], gt[3]
    maxx, miny = minx + gt[1] * ds.RasterXSize, maxy + gt[5] * ds.RasterYSize
    lon = lambda x: math.degrees(x / R_EARTH)
    lat = lambda y: math.degrees(math.atan(math.sinh(y / R_EARTH)))
    bounds_ll = (lon(minx), lat(miny), lon(maxx), lat(maxy))

    jobs = []
    for z in range(maxz, minz - 1, -1):
        tile_m = WORLD / 2 ** z
        tx0, tx1 = math.floor((minx - ORIGIN) / tile_m), math.ceil((maxx - ORIGIN) / tile_m)
        ty0, ty1 = math.floor((WORLD / 2 - maxy) / tile_m), math.ceil((WORLD / 2 - miny) / tile_m)
        rows_per = max(1, int(a.strip_px // ((tx1 - tx0) * TILE_PX * TILE_PX)))
        for r in range(ty0, ty1, rows_per):
            jobs.append((a.dem, z, tx0, tx1, r, min(r + rows_per, ty1), a.work))
    print(f"{len(jobs)} strip jobs, zooms {minz}-{maxz}, bounds {bounds_ll}", flush=True)

    strips = []
    with ThreadPoolExecutor(a.workers) as ex:
        for i, mb in enumerate(ex.map(strip_job, jobs), 1):
            strips.append(mb)
            print(f"[{i}/{len(jobs)}] {os.path.basename(mb)}", flush=True)

    mbtiles = os.path.splitext(a.out_pmtiles)[0] + ".mbtiles"
    merge(strips, mbtiles, bounds_ll, minz, maxz)
    n = sqlite3.connect(mbtiles).execute("SELECT count(*) FROM tiles").fetchone()[0]
    print(f"merged {n} tiles -> {mbtiles}", flush=True)
    if os.path.exists(a.out_pmtiles):
        os.remove(a.out_pmtiles)
    subprocess.run([os.path.expanduser("~/.local/bin/pmtiles"), "convert", mbtiles, a.out_pmtiles], check=True)
    if not a.keep_work:
        shutil.rmtree(a.work)
    print("done", a.out_pmtiles)


if __name__ == "__main__":
    main()
