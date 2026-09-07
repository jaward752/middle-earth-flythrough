# Middle-earth flythrough

Google Earth-style web app for Tolkien's Middle-earth: streamed 3D terrain, free-flying
camera, labelled vector features. Data is downloaded and verified. Toolchain is installed.
Start at "Current state".

---

## Environment

WSL2 Ubuntu on Windows. GDAL 3.12.2 (with Python bindings and numpy), tippecanoe 2.82,
go-pmtiles 1.31 at `~/.local/bin/pmtiles`. rio-rgbify is NOT installed and cannot be:
Python 3.14 has no `python3-venv` package and there is no sudo, so nothing pip-installable
is available. Everything raster is done with GDAL. Working directory `~/middle-earth`.
Windows files reachable at `/mnt/c/Users/jdw25/`. 16 cores, ~940 GB free.

Do not suggest installing QGIS-in-WSL or GUI tools. QGIS runs natively on the Windows
side for visual inspection only; all pipeline work is command line in Ubuntu.

---

## Data — verified, do not re-investigate

Source: William & Mary Center for Geospatial Analysis, "GIS & Middle Earth".
CC BY-NC-SA 4.0, DOI 10.21220/RKEZ-X707. Cite Rose, Robert A. (2020).
Attribution is required and commercial use is not permitted.

### DEM — `Quad1/` … `Quad4/`, each `DEM_50m_QuadN.tif`

Verified from `gdalinfo -stats` on Quad1:

```
Size            23017 x 17922   (412 megapixels, one quadrant)
DataType        Float32
Pixel Size      50.0 m, exactly square
Origin          (2527364.2196, 3232003.6458)
Minimum        -83.647 m
Maximum       3699.737 m
Mean           388.699
NoData         -999
```

Each quad ships with a `.ovr` overview pyramid already built. Use it; don't regenerate.

**CRS is custom.** `Middle_Earth_Conformal_Conic` — a Lambert Conformal Conic (2SP)
on the ETRS89 datum (EPSG:4258 base):

```
standard parallels     35째 and 65째
false origin           lat 52째, lon 10째
false easting          4000000 m
false northing         2800000 m
```

There is no EPSG code for this. It is embedded in the GeoTIFFs and in each shapefile's
`.prj`, so GDAL reads it without help — but nothing downstream will recognise it by name.

### Vectors — `Vector_Shapefiles/`

26 layers, same CRS as the DEM, authored as one coherent product with it:

Bays, Bridges, Buildings, Cave_entrances, Doors_Gates, Falls, Fields, Fords, Forests,
Fortresses, Frodo_Route, Graves_Tombs, Harbors, Hills, Islands, Lakes, Mountains,
Mountains_of_Moria, Place_Boundaries, Realms, Rivers, Roads, Swamps, Towns, Valleys, Walls

---

## Two traps

**NoData is -999, and it is not optional to handle.** Every `gdalwarp` and `gdalbuildvrt`
call needs `-srcnodata -999 -dstnodata -999`. Omit it and the value is read as an
elevation, producing kilometre-deep trenches along every quadrant seam.

**Tiles must be EPSG:3857 (Web Mercator).** MapLibre and every other web mapping library
expect it, and being on a real globe is what makes MapLibre's built-in terrain work
without a custom projection layer. This project does NOT warp the conic to 3857; it
relabels the conic's metres as Mercator metres centred on the equator. See "Re-anchor
to the equator" under Quality requirements for why, and for the exact offsets.

---

## Current state

Done, checked with `gdalinfo` and pixel reads on 2026-09-07:

- Pipeline steps 1-3: `me_50m.vrt`, `me_3857_anchored.vrt`, `me_3857.tif`
  (47040 x 38668, 3.6 GB, NoData filled with 0, gdalwarp exit 0, 2 min 16 s).
- Step 4 complete: `me_z12.tif` (123082 x 101176, 19.109 m, Float32, 512 px
  blocks, 17 GB, 2 min 46 s). Base band verified: centre reads 199-450 m and matches
  `me_3857.tif` at the same ground point; the top-left corner is 0 m (sea).
- Step 4 overviews complete: external `me_z12.tif.ovr` (5.1 GB, `gdaladdo -ro`,
  1 min 26 s). The earlier empty internal levels were removed with `gdaladdo -clean`.
  Verified all 12 levels: mean 268 m at every level, max 3681 m at level 0 falling
  smoothly to 1614 m at the 31 x 25 level. None reads as zero.
- `scripts/build_terrain_pmtiles.py` written (step 5).

Step 5 was launched detached on 2026-09-07 (`nohup setsid ... > pmtiles.log`):

```bash
python3 scripts/build_terrain_pmtiles.py me_z12.tif terrain.pmtiles --zooms 0-12
```

Check `pmtiles.log` for "done terrain.pmtiles". If it stopped early, `work_terrain/`
holds per-strip MBTiles; the script does not resume, so rerun it from scratch.

Next after step 5: verify `terrain.pmtiles` (`pmtiles show`, decode a z12 tile and a
z4 tile and compare against `me_z12.tif`), then step 6 vectors, then rendering.

---

## Pipeline

```bash
# 1. mosaic (above)

# 2. re-anchor: relabel conic metres as EPSG:3857 metres centred on the equator
#    (metadata only; see Quality requirements for the derivation of these numbers)
gdal_translate -of VRT -a_srs EPSG:3857 \
  -a_ullr -1176000 966700 1176000 -966700 me_50m.vrt me_3857_anchored.vrt

# 3. materialise, filling -999 NoData with 0 m (Terrain-RGB has no transparency;
#    -999 would encode as a 1 km pit). ~2 min, 47040x38668, ~3 GB.
gdalwarp -r near -te -1176000 -966700 1176000 966700 -tr 50 50 \
  -multi -wo NUM_THREADS=ALL_CPUS -srcnodata -999 -dstnodata 0 \
  -co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=YES -co NUM_THREADS=ALL_CPUS \
  me_3857_anchored.vrt me_3857.tif
gdal_edit.py -unsetnodata me_3857.tif

# 4. float DEM on the exact zoom-12 / 512 px grid (19.109 m), plus averaged overviews
#    for zooms 11..0. 123082x101176 px, ~10 min. All later zooms read from this.
RES=$(python3 -c "print(repr(40075016.68557849/(2**12*512)))")
gdalwarp -r bilinear -tr $RES $RES -tap -multi -wo NUM_THREADS=ALL_CPUS \
  -co TILED=YES -co BLOCKXSIZE=512 -co BLOCKYSIZE=512 -co COMPRESS=DEFLATE \
  -co PREDICTOR=3 -co BIGTIFF=YES -co NUM_THREADS=ALL_CPUS me_3857.tif me_z12.tif
gdaladdo -ro -r average --config GDAL_NUM_THREADS ALL_CPUS --config COMPRESS_OVERVIEW DEFLATE \
  --config PREDICTOR_OVERVIEW 3 me_z12.tif 2 4 8 16 32 64 128 256 512 1024 2048 4096

# 5. Terrain-RGB encode + tile + PMTiles (512 px, PNG, z0-12), parallel strips
python3 scripts/build_terrain_pmtiles.py me_z12.tif terrain.pmtiles --zooms 0-12

# 6. vector tiles — note -s_srs override, same offsets as step 2
mkdir -p geojson
for f in Vector_Shapefiles/*.shp; do
  n=$(basename "${f%.shp}")
  ogr2ogr -f GeoJSON -t_srs EPSG:4326 \
    -s_srs "+proj=merc +a=6378137 +b=6378137 +x_0=3703364.2196 +y_0=2265303.6458 +units=m +no_defs" \
    "geojson/$n.geojson" "$f"
done
tippecanoe -o vectors.pmtiles -Z0 -z12 --drop-densest-as-needed geojson/*.geojson
```

Intermediates: `me_3857.tif` ~3 GB, `me_z12.tif` + `.ovr` tens of GB. Keep `me_z12.tif`
until the terrain PMTiles has been checked in MapLibre; it is the input for any re-tile.

---

## Rendering

MapLibre GL JS. Terrain-RGB tiles feed its `raster-dem` source and 3D terrain directly;
vector tiles style natively; the free camera gives the flythrough. Serve `tiles/`
statically — there is no backend in this project.

Milestones, strictly in order. Do not start one before the previous renders:

1. Terrain renders, camera flies, no crash at zoom 12
2. Rivers and Bays overlaid — visual confirmation raster and vector agree
3. Roads, Forests, Lakes, Swamps as styled layers
4. Towns and Fortresses labelled, with zoom-dependent density
5. Search across place names with fly-to
6. Frodo_Route as a highlighted path — the dataset includes it, so use it

## Constraints

- Vertical exaggeration adjustable at runtime. Peaks reach 3,700 m across a continent
  ~2,000 km wide; at true scale they vanish. Expect 3-8x.
- Ship the W&M attribution in the UI. The licence requires it and forbids commercial use.
- Tolkien place names and maps are Tolkien Estate IP, enforced via HarperCollins and
  Middle-earth Enterprises. Non-commercial fan projects are broadly tolerated;
  monetising is what gets them taken down.

---

## Quality requirements — decided, do not relitigate

### Re-anchor to the equator before tiling — DONE, method below

The custom conic's false origin places this data at 36.6-56.0°N, centre 46.3°N. In Web
Mercator the scale factor there runs from 1.25x in the south to 1.79x in the north, so
the north of the map would render visibly larger than the south. Unacceptable for a
project whose goal is geographic accuracy. Middle-earth is fictional; there is no
correct real-world latitude, so nothing is lost by moving it.

**Do not do this by warping to EPSG:4326 and relabelling the degree bounds with
`gdal_edit.py -a_ullr`.** That was the original plan here and it is wrong, because it
does not preserve shape. In a lat/lon raster a 50 m east-west step spans 1/cos(lat)
more degrees than a 50 m north-south step. Translating the degree bounds to the equator,
where a degree of longitude equals a degree of latitude on the ground, turns that ratio
into a real east-west stretch: 1.79x at the old north edge, 1.45x at the centre, 1.25x
at the old south edge. That is the same north-south gradient Mercator had, but now
non-conformal, so coastlines and mountain ranges change shape rather than only size.
(A 4326 warp was run and measured before this was caught; it was deleted.)

**What was actually done: relabel the conic's metres as Web Mercator metres.** The
conic is conformal with scale within a few percent of 1, so its projected coordinates
are already near-true ground metres. Declaring them as EPSG:3857 metres centred on the
origin puts the whole map within ±8.65° of the equator, where Mercator scale error is
under 1.2% and uniform in both axes. It is a metadata-only rewrite: no resampling, no
4326 intermediate, and the pixel grid stays exactly 50 m.

Mosaic extent in the conic: x 2527364.2196..4879364.2196, y 1298603.6458..3232003.6458,
centre (3703364.2196, 2265303.6458). Translate so the centre lands on (0, 0):

```bash
# raster: rewrite the mosaic's georeferencing (VRT, instant)
gdal_translate -of VRT -a_srs EPSG:3857 \
  -a_ullr -1176000 966700 1176000 -966700 me_50m.vrt me_3857_anchored.vrt

# vectors: the identical translation, expressed as false easting/northing on a
# spherical Mercator that OVERRIDES the shapefile CRS (-s_srs is an override, not a
# reprojection); -t_srs then does the true inverse-Mercator to lon/lat
ogr2ogr -f GeoJSON -t_srs EPSG:4326 \
  -s_srs "+proj=merc +a=6378137 +b=6378137 +x_0=3703364.2196 +y_0=2265303.6458 +units=m +no_defs" \
  geojson/NAME.geojson Vector_Shapefiles/NAME.shp
```

Result: EPSG:3857 extent ±1176000 m east-west, ±966700 m north-south, i.e. lon ±10.56°,
lat ±8.65°. Raster and vectors must both use exactly these offsets or they will not
line up. The Two-traps note about "warping to 3857" is superseded by this.

### Max zoom is 12. Not 13.

At this latitude, 50 m native resolution corresponds to roughly zoom 11. Zoom 12
gives headroom. Zoom 13 quadruples tile count for detail that does not exist in the
source data.

### PMTiles, not a tile directory

A zoom 0-12 pyramid is hundreds of thousands of files. That is slow on the WSL
filesystem and awkward to deploy. Output PMTiles instead: single file, HTTP range
requests, read natively by MapLibre.

```bash
# raster — see Pipeline; rio-rgbify/rio-pmtiles are NOT installed (no python3-venv,
# no sudo), so encoding and tiling are done with GDAL + go-pmtiles instead
python3 scripts/build_terrain_pmtiles.py me_z12.tif terrain.pmtiles --zooms 0-12
# vector
tippecanoe -o vectors.pmtiles -Z0 -z12 --drop-densest-as-needed geojson/*.geojson
```

Terrain-RGB must be encoded AFTER resampling at every zoom, never resampled as RGB
bytes: the encoding packs elevation into three bytes, and averaging or interpolating
those bytes produces garbage wherever a channel wraps. The script builds each zoom from
the float DEM's averaged overviews, then encodes with a GDAL VRT `expression` pixel
function (base -10000, interval 0.1, identical to `rio rgbify -b -10000 -i 0.1`).
Each zoom is padded out to whole tiles with 0 m, so the map edge is sea level rather
than a -10000 m cliff.

### 512px tiles for terrain

Quarter the request count versus 256px. Set `tileSize: 512` on the `raster-dem`
source to match.

### Per-layer minzoom

26 layers all drawing at zoom 0 will stall the first paint. Rough tiers:

- z0+   Realms, Bays, Islands, Place_Boundaries
- z5+   Rivers, Roads, Forests, Lakes, Mountains, Swamps
- z8+   Towns, Fortresses, Harbors, Hills, Valleys, Walls
- z10+  Buildings, Bridges, Fords, Falls, Doors_Gates, Cave_entrances,
        Graves_Tombs, Fields, Mountains_of_Moria

### Serving

Do not use `python -m http.server` for anything beyond a first smoke test; it is
single-threaded and will make the app feel broken. Use `caddy file-server` or
`npx serve`, with proper cache headers on tile responses.

---

## Session discipline

`git init` and commit at each working milestone, so a lost session costs nothing.

Run `/clear` between phases (tiling done -> rendering starts). Conversation history
is resent every turn and is the main driver of both cost and context exhaustion.
CLAUDE.md reloads automatically after a clear.

The heavy compute here is local GDAL work. It consumes no tokens and is unaffected
by session limits.
