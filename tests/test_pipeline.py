import json
from pathlib import Path
from shapely.geometry import mapping, Polygon, Point
import pytest
from iris_flood.pipeline import load_geojson, normalize_features, overlay_intersections

ROOT = Path(__file__).parents[1]


def test_fixture_has_valid_and_rejected_feature():
    features = load_geojson(ROOT / "fixtures/hq100_sample.geojson")
    zones, report = normalize_features(features, source_name="fixture-only-not-official")
    assert len(zones) == 2
    assert report.input_count == 3
    assert report.accepted_count == 2
    assert report.rejected_count == 1
    assert report.rejection_reasons["non_polygon_geometry"] == 1


def test_idempotent_ids_for_same_feature_without_source_id():
    feature = {"type":"Feature", "properties":{"flood_class":"HQ100","authority":"Test"},
               "geometry": mapping(Polygon([(0,0),(1,0),(1,1),(0,1),(0,0)]))}
    first, _ = normalize_features([feature], source_name="test")
    second, _ = normalize_features([feature], source_name="test")
    assert first[0].source_id == second[0].source_id


def test_duplicate_source_ids_are_deduplicated():
    features = load_geojson(ROOT / "fixtures/hq100_sample.geojson")[:1] * 2
    zones, report = normalize_features(features, source_name="test")
    assert len(zones) == 1
    assert report.duplicate_count == 1


def test_rejects_non_hq100_scenario():
    feature = {"type":"Feature", "properties":{"source_id":"x","flood_class":"HQEXTREM"},
               "geometry": mapping(Polygon([(0,0),(1,0),(1,1),(0,1),(0,0)]))}
    zones, report = normalize_features([feature], source_name="test")
    assert not zones
    assert report.rejection_reasons["flood_class_not_confirmed_hq100"] == 1


def test_spatial_overlay_intersection():
    features = load_geojson(ROOT / "fixtures/hq100_sample.geojson")
    zones, _ = normalize_features(features, source_name="fixture")
    parcel = json.loads((ROOT / "fixtures/parcel_sample.geojson").read_text())
    hits = overlay_intersections(zones, parcel)
    assert hits == ["fixture-zone-001"]


def test_invalid_parcel_fails_closed():
    features = load_geojson(ROOT / "fixtures/hq100_sample.geojson")
    zones, _ = normalize_features(features, source_name="fixture")
    with pytest.raises(ValueError):
        overlay_intersections(zones, mapping(Point(0, 0)))


def test_database_target_guard():
    from iris_flood.db import validate_database_url
    validate_database_url("postgresql+psycopg://iris_staging:local@localhost:5432/iris_staging")
    validate_database_url("postgresql+psycopg://iris_staging:local@postgis:5432/iris_staging")
    with pytest.raises(ValueError):
        validate_database_url("postgresql+psycopg://user:pw@db/iris_core")
    with pytest.raises(ValueError):
        validate_database_url("postgresql+psycopg://user:pw@remote/db")
    with pytest.raises(ValueError):
        validate_database_url("postgresql+psycopg://user:pw@localhost:5432/other_db")


def test_vector_loader_reprojects_and_reports_crs():
    from iris_flood.pipeline import load_vector_source
    features, crs = load_vector_source(ROOT / "fixtures/hq100_sample.geojson")
    assert "4326" in crs
    assert len(features) == 3
    assert features[0]["geometry"]["type"] == "Polygon"


def test_missing_flood_class_is_rejected_unless_source_explicitly_confirmed():
    feature = {"type":"Feature", "properties":{"source_id":"no-class"},
               "geometry": mapping(Polygon([(0,0),(1,0),(1,1),(0,1),(0,0)]))}
    zones, report = normalize_features([feature], source_name="test")
    assert not zones
    assert report.rejection_reasons["missing_flood_class"] == 1
    zones, _ = normalize_features([feature], source_name="test", assume_hq100_source=True)
    assert zones[0].flood_class == "HQ100"
