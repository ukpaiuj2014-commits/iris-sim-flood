"""Source-agnostic normalization and validation for HQ100 polygon ingestion."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.validation import explain_validity, make_valid

LOG = logging.getLogger(__name__)
POLYGON_TYPES = {"Polygon", "MultiPolygon"}


@dataclass(frozen=True)
class NormalizedZone:
    source_id: str
    source_id_original: str
    flood_class: str
    authority: str
    source_date: str | None
    source_name: str
    source_url: str | None
    source_crs: str
    geometry: dict[str, Any]
    geometry_hash: str


@dataclass
class QualityReport:
    source_name: str
    source_url: str | None
    authority: str = "UNCONFIRMED"
    input_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    repaired_count: int = 0
    duplicate_source_id_count: int = 0
    rejection_reasons: dict[str, int] | None = None
    accepted_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.rejection_reasons is None:
            self.rejection_reasons = {}
        if self.accepted_ids is None:
            self.accepted_ids = []

    def reject(self, reason: str) -> None:
        self.rejected_count += 1
        assert self.rejection_reasons is not None
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _first(props: dict[str, Any], candidates: Iterable[str]) -> Any:
    lower = {str(k).lower(): v for k, v in props.items()}
    for key in candidates:
        value = lower.get(key.lower())
        if value is not None and str(value).strip():
            return value
    return None


def _stable_id(
    props: dict[str, Any],
    geom_text: str,
    authority: str,
    flood_class: str,
) -> str:
    """Return a stable feature ID, including for distinct geometry components."""
    original = _first(
        props,
        (
            "source_id", "apsfr_code", "gml_id", "objectid",
            "object_id", "fid", "id", "uuid",
        ),
    )
    if original is None:
        seed = json.dumps(
            {
                "geometry": json.loads(geom_text),
                "authority": authority,
                "flood_class": flood_class,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()

    original = str(original).strip()
    # Geometry fingerprint prevents distinct features with one official ID
    # from colliding, while repeated copies of the same feature remain stable.
    fingerprint = hashlib.sha256(geom_text.encode("utf-8")).hexdigest()[:16]
    return original


def normalize_features(features: list[dict[str, Any]], *, source_name: str,
                       source_url: str | None = None, source_crs: str = "EPSG:4326",
                       default_authority: str = "UNCONFIRMED", assume_hq100_source: bool = False) -> tuple[list[NormalizedZone], QualityReport]:
    """Normalize GeoJSON-like features; no database side effects occur here."""
    report = QualityReport(
    source_name=source_name,
    source_url=source_url,
    authority=default_authority,
    input_count=len(features),
)
    accepted: list[NormalizedZone] = []
    seen: dict[str, str] = {}
    for index, feature in enumerate(features):
        try:
            props = feature.get("properties") or {}
            raw_geom = feature.get("geometry")
            if not isinstance(props, dict):
                report.reject("properties_not_object"); continue
            if not raw_geom:
                report.reject("missing_geometry"); continue
            geom = shape(raw_geom)
            if geom.geom_type not in POLYGON_TYPES:
                report.reject("non_polygon_geometry"); continue
            if geom.is_empty:
                report.reject("empty_geometry"); continue
            if not geom.is_valid:
                geom = make_valid(geom)
                if geom.is_empty:
                    report.reject("repair_empty_geometry")
                    continue
                if geom.geom_type not in POLYGON_TYPES:
                    report.reject("repair_non_polygon_geometry")
                    continue
                if not geom.is_valid:
                    report.reject("repair_still_invalid")
                    continue
                report.repaired_count += 1
            flood_class = _clean_text(_first(props, ("flood_class", "fl_recur", "scenario", "hazard_type", "return_period", "HQ", "klasse")))
            if flood_class is None:
                if assume_hq100_source:
                    flood_class = "HQ100"
                else:
                    report.reject("missing_flood_class")
                    continue
            # Only retain HQ100/medium-probability features; don't silently mislabel other scenarios.
            norm_class = flood_class.upper().replace(" ", "")
            if not any(token in norm_class for token in ("HQ100", "HQ_100", "100YEAR", "MEDIUM")):
                report.reject("flood_class_not_confirmed_hq100"); continue
            authority = _clean_text(_first(props, ("authority", "publisher", "agency", "source_authority"))) or default_authority
            date_value = _first(props, ("source_date", "valid_from", "updated", "date", "datum"))
            source_date = None
            if date_value is not None:
                source_date = str(date_value).strip()[:10]
                try:
                    datetime.fromisoformat(source_date)
                except ValueError:
                    report.reject("malformed_source_date"); continue
            geom_text = json.dumps(mapping(geom), sort_keys=True, separators=(",", ":"))
            original_id = _clean_text(
                _first(props, ("source_id", "apsfr_code", "gml_id", "objectid",
                               "object_id", "fid", "id", "uuid"))
            )
            sid = _stable_id(props, geom_text, authority, "HQ100")
            geometry_fingerprint = hashlib.sha256(
                geom_text.encode("utf-8")
            ).hexdigest()[:16]

            # Preserve the original ID for unique features. If an ID repeats
            # with different geometry, retain each component deterministically.
            if sid in seen:
                previous_fingerprint = seen[sid]
                if previous_fingerprint == geometry_fingerprint:
                    report.duplicate_count += 1
                    continue

                report.duplicate_source_id_count += 1
                sid = f"{sid}::{geometry_fingerprint}"

            seen[sid] = geometry_fingerprint
            accepted.append(NormalizedZone(
                source_id=sid,
                source_id_original=original_id or sid,
                flood_class="HQ100", authority=authority,
                source_date=source_date, source_name=source_name, source_url=source_url,
                source_crs=source_crs, geometry=mapping(geom),
                geometry_hash=hashlib.sha256(geom.wkb).hexdigest(),
            ))
        except (TypeError, ValueError, KeyError) as exc:
            LOG.warning("Rejecting feature index=%s reason=malformed_feature error=%s", index, exc)
            report.reject("malformed_feature")
    report.accepted_count = len(accepted)
    report.accepted_ids = [z.source_id for z in accepted]
    return accepted, report


def load_geojson(path: str | Path) -> list[dict[str, Any]]:
    """Read a GeoJSON FeatureCollection without requiring a network connection."""
    with Path(path).open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
        raise ValueError("Input must be a GeoJSON FeatureCollection")
    return document["features"]



def load_vector_source(source: str | Path) -> tuple[list[dict[str, Any]], str]:
    """Load a local or remotely accessible vector dataset and reproject geometries to EPSG:4326.

    GeoPandas/Fiona-supported formats (for example GeoJSON, GeoPackage, Shapefile ZIP, and GML)
    can be supplied as a path or URL. CRS must be present in the source; guessing a missing CRS
    would make the coordinates unsafe for spatial overlay.
    """
    frame = gpd.read_file(str(source))
    if frame.empty:
        raise ValueError("Source dataset contains no features")
    if frame.crs is None:
        raise ValueError("Source CRS is missing; refusing to guess coordinate reference system")
    original_crs = frame.crs.to_string()
    frame = frame.to_crs("EPSG:4326")
    features: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        props = {}
        for key, value in row.items():
            if key == frame.geometry.name:
                continue
            if value is None:
                props[key] = None
            elif hasattr(value, "isoformat"):
                props[key] = value.isoformat()
            else:
                try:
                    # Normalize numpy scalar values to JSON-safe Python values.
                    props[key] = value.item() if hasattr(value, "item") else value
                except (ValueError, TypeError):
                    props[key] = str(value)
        geom = row[frame.geometry.name]
        features.append({"type": "Feature", "properties": props,
                         "geometry": None if geom is None else mapping(geom)})
    return features, original_crs


def overlay_intersections(zones: list[NormalizedZone], parcel_geojson: dict[str, Any]) -> list[str]:
    """Return source IDs of zones intersecting a parcel fixture; uses planar geometry intersection."""
    parcel = shape(parcel_geojson)
    if parcel.geom_type not in POLYGON_TYPES or parcel.is_empty or not parcel.is_valid:
        raise ValueError("Parcel geometry must be a non-empty, valid Polygon or MultiPolygon")
    return [zone.source_id for zone in zones if shape(zone.geometry).intersects(parcel)]


def write_report(report: QualityReport, output_path: str | Path) -> None:
    payload = report.to_dict()
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
