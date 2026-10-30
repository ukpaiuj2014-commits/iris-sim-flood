# IRIS-SIM-FLOOD — LAWA HQ100 Flood Zone Ingestion

Task ID: `TASK 103 | IRIS-SIM-FLOOD`

A reproducible Python workflow for validating HQ100 flood-zone polygons and loading them into the isolated PostGIS staging table `iris_staging.flood_zones_hq100`. The loader validates geometries, normalizes source fields, records provenance, handles duplicate source identifiers, and uses repeatable upserts.

The workflow is designed for staging only. It does not write to `iris_core` or a production schema.

## Source selection and provenance

### National source candidate: BfG

The Federal Institute of Hydrology (BfG) national INSPIRE Natural Risk Zones service, coordinated with LAWA, is a candidate source for the assignment because the task does not specify a German federal state.

References:

- [BfG dataset record](https://geoportal.bafg.de/csw-client/recordbyid?id=bfg&lang=de&recordid=6b2ebfe3-d47f-464d-93ff-b848ab55de05)
- [WFS GetCapabilities](https://geoportal.bafg.de/arcgis1/rest/services/INSPIRE/NZ/MapServer/exts/InspireFeatureDownload/service?REQUEST=GetCapabilities&SERVICE=WFS&VERSION=2.0.0)
- [BfG download service feed](https://geoportal.bafg.de/inspire/download/NZ/servicefeed.xml)

**Limitation:** this repository has not completed a live download and validation of the national BfG feed. The BfG source is a documented candidate, not evidence of successful ingestion of current nationwide data. National harmonization and coverage limitations described by the source metadata should be considered before operational use.

### Real-data validation: NLWKN Lower Saxony

A separate validation run used the official Lower Saxony flood-risk dataset:

- Dataset: `Hochwasserrisikogebiete HQ100 2. Zyklus`
- Provider: Niedersächsischer Landesbetrieb fuer Wasserwirtschaft, Kuesten- und Naturschutz (NLWKN)
- Reporting cycle: 2016-2021
- Download: [Official NLWKN HQ100 dataset ZIP](https://www.umweltkarten.niedersachsen.de/Download_OE/HWSchutz/HWRMRL_Z2_Risikogebiete_HQ100.zip)
- Metadata: [Lower Saxony metadata record](https://umweltportal.niedersachsen.de/suche/detail?id=numis-metadaten-bf19e392-8500-44b7-976e-17a8c11fc445)
- Source CRS: EPSG:4647 (ETRS89 / UTM zone 32N)
- Storage CRS: EPSG:4326

This is historical, regional data. It is not a current national flood-risk dataset and must not be presented as current flood-risk advice.

### Licence and attribution

The supplied NLWKN licence document describes the `Datenlizenz Deutschland - Namensnennung - Version 2.0` (DL-DE-BY-2.0).

- Licence: https://www.govdata.de/dl-de/by-2-0
- Provider information: https://www.nlwkn.niedersachsen.de/opendata
- Attribution: `2026 NLWKN` and `www.nlwkn.niedersachsen.de/opendata`

Retain the licence document and attribution when redistributing the dataset. Review the source licence and disclaimer before any other use.

The included `hq100_sample.geojson` is synthetic fixture data for automated tests. It is not official flood-zone data.

## Real-data validation results

The NLWKN source was loaded for validation and ingested into the isolated PostGIS staging database.

| Check | Result |
|---|---:|
| Input features | 45 |
| Accepted features | 45 |
| Rejected features | 0 |
| Geometries repaired | 13 |
| Repeated original source IDs detected | 1 |
| Final staging rows after repeat ingestion | 45 |
| Distinct staging IDs | 45 |
| Valid geometries in EPSG:4326 with flood class HQ100 | 45 |

One original source identifier, `DENI_RG_594_TEL_IES`, occurred on two different valid polygon components. The ingestion logic retained both components and assigned a deterministic geometry-fingerprint suffix to the second ID. They were not discarded as identical duplicate geometries.

The ingestion was run twice. After the second run, a read-only PostGIS query confirmed 45 total rows, 45 distinct source IDs, and 45 rows with valid geometries, SRID 4326, and flood class HQ100.

The machine-readable validation report is available at `reports/niedersachsen_hq100_quality.json`.

These results demonstrate successful ingestion of this specific regional dataset into the local staging database. They do not establish that the BfG national feed was ingested or that the data represent current flood conditions.

## Requirements

- Python 3.11 or newer
- Docker Desktop with Docker Compose for the PostGIS integration run

Install and run the tests:

```bash
python -m venv .venv
# Windows CMD:
.venv\Scripts\activate
python -m pip install -e ".[test]"
python -m pytest -q
```

The CLI accepts a local vector file or a GeoPandas-readable source. It requires a declared CRS and reprojects geometries to EPSG:4326 before storage. The `--validate-only` option validates the input and writes a machine-readable report without connecting to the database.

Example validation command for the NLWKN shapefile:

```bash
python -m iris_flood.cli --source "fixtures/niedersachsen_hq100/Risikogebiete_HQ100_Z2.shp" --source-name "NLWKN Niedersachsen HQ100 (historical 2016-2021)" --source-url "https://www.umweltkarten.niedersachsen.de/Download_OE/HWSchutz/HWRMRL_Z2_Risikogebiete_HQ100.zip" --validate-only --report "reports/niedersachsen_hq100_quality.json"
```

## Isolated PostGIS staging

Start the database:

```bash
docker compose up -d postgis
```

The local Compose configuration binds PostGIS to `127.0.0.1:55433` to avoid conflicting with another local project. It uses a dedicated `iris_staging` database and user. The local development password is not suitable for deployment; configure secrets appropriately for any non-local environment.

Run the NLWKN ingestion:

```bash
docker compose run --rm ingest iris-flood-ingest --source "fixtures/niedersachsen_hq100/Risikogebiete_HQ100_Z2.shp" --source-name "NLWKN Niedersachsen HQ100 (historical 2016-2021)" --source-url "https://www.umweltkarten.niedersachsen.de/Download_OE/HWSchutz/HWRMRL_Z2_Risikogebiete_HQ100.zip" --report "reports/niedersachsen_hq100_quality.json"
```

Verify the staging rows:

```bash
docker compose exec postgis psql -U iris_staging -d iris_staging -c "SELECT COUNT(*) AS total_rows, COUNT(DISTINCT source_id) AS distinct_ids, COUNT(*) FILTER (WHERE ST_IsValid(geom) AND ST_SRID(geom)=4326 AND flood_class='HQ100') AS valid_hq100_rows FROM iris_staging.flood_zones_hq100;"
```

The expected result for the validated NLWKN dataset is 45 rows, 45 distinct IDs, and 45 valid HQ100 geometries in EPSG:4326.

## Field mapping and validation

| Destination field | Mapping or rule |
|---|---|
| `source_id` | Source identifier when available; duplicate identifiers with different geometries are disambiguated using a geometry fingerprint |
| `source_id_original` | Original identifier from the source |
| `flood_class` | Normalized to `HQ100` when the source value qualifies |
| `authority` | Source authority field when available; otherwise the configured fallback |
| `source_date` | Parsed source date when available |
| `source_name`, `source_url` | Run configuration used for provenance |
| `source_crs` | CRS detected from the input vector source |
| `geometry_hash` | Geometry fingerprint for change and audit comparisons |
| `geom` | Valid polygon or multipolygon stored as PostGIS MultiPolygon with SRID 4326 |

Invalid polygon geometries are repaired with Shapely where possible. Empty, non-polygonal, or still-invalid geometries are rejected. The loader uses an upsert keyed by `source_id` so repeated runs do not add new rows for the same IDs.

## Automated tests and limitations

Automated tests cover geometry validation, duplicate source identifiers, deterministic fallback identifiers, rejection of non-HQ100 features, and polygon intersection. Run the test suite with `python -m pytest -q`.

This workflow is a staging ingestion exercise, not a certified flood-risk assessment. Before operational use, verify the target jurisdiction, current source endpoint, licensing, feature coverage, source dates, and expected CRS. Compare downloaded feature counts and geographic extents with the source metadata. Historical regional data must not be interpreted as a current national flood-risk map.
