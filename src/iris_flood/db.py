
"""Safe, idempotent PostGIS staging writer."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .pipeline import NormalizedZone

LOG = logging.getLogger(__name__)
SCHEMA = "iris_staging"
TABLE = "flood_zones_hq100"


def validate_database_url(database_url: str) -> None:
    """Fail closed unless the connection explicitly targets isolated staging."""
    if not database_url:
        raise ValueError("DATABASE_URL is required")

    lowered = database_url.lower()
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/").split("/", 1)[0].lower()
    allowed_hosts = {"localhost", "127.0.0.1", "postgis"}

    if any(token in lowered for token in ("iris_core", "production", "prod")):
        raise ValueError("Refusing database URL that appears to target core/production")

    if database_name != "iris_staging" or parsed.hostname not in allowed_hosts:
        raise ValueError(
            "DATABASE_URL must target database iris_staging "
            "on an isolated local/PostGIS host"
        )


def make_engine(database_url: str) -> Engine:
    validate_database_url(database_url)
    return create_engine(database_url, pool_pre_ping=True)


def ensure_table(engine: Engine) -> None:
    """Create the staging table and add the provenance column if needed."""
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS iris_staging"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS iris_staging.flood_zones_hq100 (
              source_id TEXT PRIMARY KEY,
              source_id_original TEXT,
              flood_class TEXT NOT NULL CHECK (flood_class = 'HQ100'),
              authority TEXT NOT NULL,
              source_date DATE NULL,
              source_name TEXT NOT NULL,
              source_url TEXT NULL,
              source_crs TEXT NOT NULL,
              geometry_hash TEXT NOT NULL,
              geom geometry(MultiPolygon, 4326) NOT NULL,
              ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        # Backward-compatible migration if the table already exists.
        conn.execute(text("""
            ALTER TABLE iris_staging.flood_zones_hq100
            ADD COLUMN IF NOT EXISTS source_id_original TEXT
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_flood_zones_hq100_geom
            ON iris_staging.flood_zones_hq100 USING GIST (geom)
        """))


def upsert_zones(engine: Engine, zones: list[NormalizedZone]) -> int:
    """Upsert by deterministic feature ID, preserving source provenance."""
    ensure_table(engine)

    statement = text("""
      INSERT INTO iris_staging.flood_zones_hq100
        (source_id, source_id_original, flood_class, authority, source_date,
         source_name, source_url, source_crs, geometry_hash, geom)
      VALUES
        (:source_id, :source_id_original, :flood_class, :authority,
         CAST(:source_date AS DATE), :source_name, :source_url, :source_crs,
         :geometry_hash,
         ST_Multi(ST_SetSRID(ST_GeomFromWKB(:wkb), 4326)))
      ON CONFLICT (source_id) DO UPDATE SET
        source_id_original=EXCLUDED.source_id_original,
        flood_class=EXCLUDED.flood_class,
        authority=EXCLUDED.authority,
        source_date=EXCLUDED.source_date,
        source_name=EXCLUDED.source_name,
        source_url=EXCLUDED.source_url,
        source_crs=EXCLUDED.source_crs,
        geometry_hash=EXCLUDED.geometry_hash,
        geom=EXCLUDED.geom,
        ingested_at=now()
    """)

    from shapely.geometry import shape

    rows = []
    for zone in zones:
        geom = shape(zone.geometry)

        if geom.is_empty or not geom.is_valid:
            raise ValueError(
                f"Refusing invalid or empty geometry for source_id={zone.source_id}"
            )
        if geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Refusing non-polygon geometry for source_id={zone.source_id}"
            )

        rows.append({
            "source_id": zone.source_id,
            "source_id_original": zone.source_id_original,
            "flood_class": zone.flood_class,
            "authority": zone.authority,
            "source_date": zone.source_date,
            "source_name": zone.source_name,
            "source_url": zone.source_url,
            "source_crs": zone.source_crs,
            "geometry_hash": zone.geometry_hash,
            "wkb": geom.wkb,
        })

    with engine.begin() as conn:
        if rows:
            conn.execute(statement, rows)

    LOG.info(
        "staging_upsert_complete table=%s.%s count=%d",
        SCHEMA, TABLE, len(rows)
    )
    return len(rows)
