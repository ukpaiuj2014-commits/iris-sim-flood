from __future__ import annotations
import argparse
import logging
import os
from dotenv import load_dotenv
from .pipeline import load_vector_source, normalize_features, write_report
from .db import make_engine, upsert_zones


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Validate and ingest HQ100 flood polygons into iris_staging only")
    parser.add_argument("--source", default=os.getenv("SOURCE_PATH", "fixtures/hq100_sample.geojson"))
    parser.add_argument("--source-name", default=os.getenv("SOURCE_NAME", "fixture-only-not-official"))
    parser.add_argument("--source-url", default=os.getenv("SOURCE_URL") or None)
    parser.add_argument("--authority", default=os.getenv("DEFAULT_AUTHORITY", "UNCONFIRMED"),help="Default authority when the source has no authority field")
    parser.add_argument("--assume-hq100-source", action="store_true", help="Use only after verifying the source contains exclusively HQ100 features")
    parser.add_argument("--report", default="reports/quality-report.json")
    parser.add_argument("--validate-only", action="store_true", help="Run validation/report only; do not connect to a database")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    features, discovered_crs = load_vector_source(args.source)
    zones, report = normalize_features(
    features,
    source_name=args.source_name,
    source_url=args.source_url,
    source_crs=discovered_crs,
    default_authority=args.authority,
    assume_hq100_source=args.assume_hq100_source,
)
    write_report(report, args.report)
    logging.info("quality_summary input=%d accepted=%d rejected=%d duplicates=%d", report.input_count, report.accepted_count, report.rejected_count, report.duplicate_count)
    if not args.validate_only:
        database_url = os.getenv("DATABASE_URL", "")
        engine = make_engine(database_url)
        count = upsert_zones(engine, zones)
        logging.info("staging_rows_upserted=%d", count)
    return 0 if report.accepted_count > 0 else 2

if __name__ == "__main__":
    raise SystemExit(main())
