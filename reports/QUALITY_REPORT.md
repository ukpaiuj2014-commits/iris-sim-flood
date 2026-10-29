# Initial data-quality report

**Status:** fixture validation only. No live official source ingestion has been asserted.

The included GeoJSON contains two synthetic valid HQ100 polygons and one synthetic point intentionally supplied as a bad geometry. The expected validation result is 3 input features, 2 accepted polygons, 1 rejected non-polygon, and no duplicate IDs. A separate parcel fixture intersects only `fixture-zone-001`. The automated test suite passes locally: **9 passed**.

## Source decision and evidence status

The selected primary source candidate is the official BfG national INSPIRE Natural Risk Zones WFS, coordinated with LAWA, for the 2022–2027 reporting cycle. Its official metadata says that data are supplied by German state authorities and nationally harmonised; it also warns that state-level services may be more current/detailed and that national coverage is not guaranteed. The assignment does not specify a state. See the [BfG metadata](https://geoportal.bafg.de/csw-client/recordbyid?id=bfg&lang=de&recordid=6b2ebfe3-d47f-464d-93ff-b848ab55de05) and [WFS GetCapabilities](https://geoportal.bafg.de/arcgis1/rest/services/INSPIRE/NZ/MapServer/exts/InspireFeatureDownload/service?REQUEST=GetCapabilities&SERVICE=WFS&VERSION=2.0.0).

**No live official dataset was downloaded or validated in this environment.** The reported counts above are fixture-test counts only, not official source coverage. Do not claim a successful live ingestion until the WFS response/schema, scenario encoding, CRS, and actual feature counts have been checked. If the intended state is subsequently specified, prefer the current official state service.

## Known limitations / release blockers

- The fixture is explicitly synthetic and must not be represented as official LAWA/state data.
- Before representing the ingestion as live-source complete, verify endpoint access, WFS feature type and attributes, licence/attribution, source timestamp, CRS, scenario mapping, and geographic coverage from authoritative metadata.
- The loader now requires source CRS metadata and reprojects loaded vector features to EPSG:4326. Sources with missing CRS are rejected rather than guessed.
- Only polygon/multipolygon HQ100 features are accepted. Other flood scenarios and missing scenario fields are rejected by default; an explicit opt-in exists only for verified HQ100-only sources.
- This is a preliminary parcel-screening ingestion, not certified engineering or legal flood-risk advice.
