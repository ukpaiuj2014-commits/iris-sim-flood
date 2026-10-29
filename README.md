# IRIS-SIM-FLOOD — LAWA HQ100 Flood Zone Ingestion

Task ID: `TASK 103 | IRIS-SIM-FLOOD`

A small, reproducible Python workflow that validates HQ100 polygon features and, when explicitly configured, upserts them into the isolated PostGIS staging table `iris_staging.flood_zones_hq100`. It does not write to `iris_core` or any production schema.

## Source decision and provenance

**Chosen primary candidate: BfG national INSPIRE Natural Risk Zones service, coordinated with LAWA, reporting cycle 2022–2027.** This is the most defensible default because the assignment names LAWA but does not name a federal state. The official BfG metadata identifies the national reporting dataset and the WFS download service, and says the data are supplied by the German states and harmonised nationally. Metadata: [BfG dataset record](https://geoportal.bafg.de/csw-client/recordbyid?id=bfg&lang=de&recordid=6b2ebfe3-d47f-464d-93ff-b848ab55de05); [WFS GetCapabilities](https://geoportal.bafg.de/arcgis1/rest/services/INSPIRE/NZ/MapServer/exts/InspireFeatureDownload/service?REQUEST=GetCapabilities&SERVICE=WFS&VERSION=2.0.0); [download service feed](https://geoportal.bafg.de/inspire/download/NZ/servicefeed.xml).

**Important limitation:** the BfG metadata explicitly warns that the national harmonised dataset may not be as current or detailed as the relevant state authority's data, and that complete national coverage is not guaranteed. The task does not specify a state or a live endpoint, so this is a reasoned source choice—not proof that IRIS expects this exact service. If the reviewer later confirms a state, prefer its official current HQ100 service and document the switch. For example, [Lower Saxony NLWKN HQ100 metadata](https://umweltportal.niedersachsen.de/suche/detail?id=numis-metadaten-bf19e392-8500-44b7-976e-17a8c11fc445) identifies a public dataset for the 2016–2021 cycle, but it is older and therefore not selected as the default.

The included GeoJSON is **synthetic demonstration data only**, not downloaded LAWA/BfG/NLWKN data. The live WFS has not been downloaded or validated in this environment. Do not report live-source feature counts, coverage, or successful official ingestion. For BfG data, preserve the requested attribution: “WasserBLIcK/BfG und Zuständige Behörden der Länder, [data retrieval date]”. The national dataset is available under the German Geodata Use Ordinance conditions described in its metadata.

## Local validation

Python 3.11+ is required.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
iris-flood-ingest --validate-only
```

The CLI accepts a local vector file or a GeoPandas-readable URL (GeoJSON, GeoPackage, Shapefile ZIP, GML, etc.). It requires a declared CRS and reprojects the geometries to EPSG:4326 before validation. The CLI writes a machine-readable report to `reports/quality-report.json`. `--validate-only` never opens a database connection.

## Isolated PostGIS staging run

```bash
cp .env.example .env
# Review DATABASE_URL and use only a disposable/staging database.
docker compose up --build
```

The Compose database is bound to localhost port `55432`, uses a dedicated `iris_staging` database/user, and is not connected to any external system. Change the local password before use. Never set a production URL. The writer checks that the database is named `iris_staging` and the host is a local/PostGIS Compose host; it writes only to the hard-coded `iris_staging.flood_zones_hq100` table. The upsert key is `source_id`; repeat runs update existing IDs instead of creating duplicates.

## Field mapping

| Destination | Source mapping / rule |
|---|---|
| `source_id` | First available source ID (`source_id`, `gml_id`, `objectid`, `fid`, `id`, etc.); otherwise deterministic SHA-256 over geometry and core attributes |
| `flood_class` | Accepted only when source value indicates HQ100/100-year/medium-probability; normalized to `HQ100` |
| `authority` | `authority`, `publisher`, `agency`, or `source_authority`; otherwise `UNCONFIRMED` |
| `source_date` | First available source date field, parsed as ISO date; malformed dates are rejected |
| `source_name`, `source_url` | Run configuration for provenance |
| `source_crs` | Detected input CRS is recorded; geometries are reprojected to EPSG:4326 before storage |
| `geometry_hash` | SHA-256 of geometry WKB for change/audit comparisons |
| `geom` | Valid polygon/multipolygon stored as PostGIS MultiPolygon SRID 4326 |

## Acceptance evidence and limitations

Automated tests cover invalid geometry type, duplicate source IDs, deterministic fallback IDs, non-HQ100 rejection, and parcel/polygon intersection. These are fixture-based checks, not proof that a live official feed has been downloaded. See `reports/QUALITY_REPORT.md`.

Before representing the ingestion as complete against a real authority, verify the actual target state, source endpoint and licence; confirm source CRS and reproject to EPSG:4326 where needed; run a small live sample; compare feature counts/extents/timestamps to source metadata; and record the query/run evidence. The tool is for preliminary screening only, not certified flood engineering advice.
