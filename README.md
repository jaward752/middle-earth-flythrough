# Middle-earth Flythrough

A Google Earth-style 3D map of Tolkien's Middle-earth that runs in the browser. Streamed 3D terrain, a free-flying camera, and 26 labelled map layers, including rivers, roads, realms, towns and Frodo's route.

Built with Python, GDAL, tippecanoe and MapLibre GL JS. There is no backend: the app is a static page that reads tiles directly from two PMTiles files.

## What it does

- **3D terrain** from a 50 m digital elevation model, with hillshading, elevation colouring and an adjustable vertical exaggeration (default 4x, since 3,700 m peaks across a 2,000 km continent are almost flat at true scale)
- **26 vector layers** styled at zoom-dependent levels of detail, with a coastline derived from the elevation data
- **Labels** in a serif face, with towns sized by importance (capital, city, town, village) and realms and mountain ranges in spaced capitals
- **Layer toggles** for water, roads, labels and Frodo's route

## Data pipeline

The source data is four elevation quadrants (about 1.6 billion pixels in total) and 26 shapefiles, all in a custom Lambert Conformal Conic projection with no EPSG code.

1. **Mosaic** the four elevation quadrants into one raster, handling the `-999` NoData value explicitly so quadrant seams don't become kilometre-deep trenches.
2. **Re-anchor to the equator.** Web map tiles must be Web Mercator, but at the data's original latitude (37–56°N) Mercator would stretch the north of the map by up to 1.8x. Middle-earth is fictional, so the conic's metres are relabelled as Mercator metres centred on the equator. That keeps the whole map within ±8.65° latitude, where scale error is under 1.2%. This is a metadata-only change, with no resampling.
3. **Resample** to the exact zoom-12 tile grid (19.1 m per pixel) and build averaged overviews for zooms 0–11.
4. **Encode terrain tiles** (`scripts/build_terrain_pmtiles.py`). Elevation is resampled as floating point at every zoom and only then packed into Terrain-RGB, because averaging the packed bytes produces garbage. Strips are built in parallel and merged into a single 3.75 GB PMTiles file (z0–12, 64,373 tiles). A z12 tile decodes to within 0.05 m of the source.
5. **Build vector tiles** (`scripts/build_vectors.py`). The shapefiles get the identical re-anchoring, so they line up with the terrain, and are tiled into a 7.3 MB PMTiles file. Towns are ranked from their free-text type field, and label points are generated for realms and mountain ranges.

## Running it

The tiles are generated from the source data and are not committed (about 4 GB).

1. Download the source data (see Data and licence below) and run the pipeline steps.
2. Serve the app:
   ```bash
   cd app && npx serve -l 8080 -S -n .
   ```
3. Open http://localhost:8080/.

## Repository structure

```
app/index.html                    MapLibre app: style, layers, controls
app/vendor/                       MapLibre GL JS 5.6.0 and pmtiles 4.3.0 (vendored, no CDN)
app/fonts/                        Libre Baskerville glyphs for labels
scripts/build_terrain_pmtiles.py  Terrain-RGB encoding and PMTiles build
scripts/build_vectors.py          Shapefiles to GeoJSON to vector PMTiles
scripts/slow_pixel.py             Helper for headless browser screenshot testing
```

## Status

Done: terrain, coastline, rivers, roads, forests, lakes, labelled towns and fortresses, and Frodo's route.
Next: search across place names with fly-to.

## Data and licence

Elevation and vector data: Rose, Robert A. (2020). *GIS & Middle Earth*. William & Mary Center for Geospatial Analysis. DOI [10.21220/RKEZ-X707](https://doi.org/10.21220/RKEZ-X707). Licensed CC BY-NC-SA 4.0: attribution required, no commercial use.

This is a non-commercial fan project. Tolkien place names and maps are the intellectual property of the Tolkien Estate.
