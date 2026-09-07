# Middle-earth flythrough

Google Earth-style web app for Tolkien's Middle-earth: streamed 3D terrain, free-flying
camera, labelled vector features. Data is downloaded and verified. Toolchain is installed.
Start at "Current state".

---

## Environment

WSL2 Ubuntu on Windows. GDAL 3.12.2, tippecanoe, rio-rgbify all installed and working.
Working directory `~/middle-earth`. Windows files reachable at `/mnt/c/Users/jdw25/`.

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

**Reprojection is required before tiling.** MapLibre and every other web mapping library
expect EPSG:3857 (Web Mercator). The custom conic must be warped first. Warping also
places Middle-earth on a real globe, which is what makes MapLibre's built-in terrain
work without a custom projection layer.

---

## Current state

Done: data downloaded, extracted, verified. Toolchain installed.

Next: build the VRT mosaic, check its dimensions, then warp to 3857.

```bash
cd ~/middle-earth
gdalbuildvrt -srcnodata -999 -vrtnodata -999 me_50m.vrt Quad*/DEM_50m_Quad*.tif
gdalinfo me_50m.vrt | grep -E "Size is|Pixel Size"
```

Sanity-check that size before warping. Four quads at ~23k x 18k should mosaic to roughly
40-46k on a side. Much larger means the quads have gaps or don't abut cleanly, and that
needs solving before spending 40 minutes on a reprojection.

---

## Pipeline

```bash
# 1. mosaic (above)

# 2. reproject to Web Mercator
gdalwarp -t_srs EPSG:3857 -r bilinear -multi -wo NUM_THREADS=ALL_CPUS \
  -srcnodata -999 -dstnodata -999 \
  -co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=YES \
  me_50m.vrt me_3857.tif

# 3. encode elevation into Terrain-RGB
rio rgbify -b -10000 -i 0.1 me_3857.tif me_terrain_rgb.tif

# 4. raster tile pyramid
gdal2tiles.py --xyz --zoom=0-12 --processes=4 me_terrain_rgb.tif tiles/terrain

# 5. vector tiles
cd Vector_Shapefiles
for f in *.shp; do
  ogr2ogr -f GeoJSON -t_srs EPSG:4326 "../geojson/${f%.shp}.geojson" "$f"
done
cd ..
tippecanoe -o vectors.mbtiles -Z0 -z12 --drop-densest-as-needed geojson/*.geojson
```

Step 2 is the long one. Expect tens of minutes and a large intermediate file — check free
disk before starting, the warped GeoTIFF will be several GB.

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
