"""
telemetry/forwarders/elastic_shipper.py

Ships NormalizedEvent records from JSONL evidence files to Elasticsearch using
bulk ingest. Reads file_events.jsonl and auth_events.jsonl, batches them, and
sends them to an Elasticsearch cluster.

Env vars:
  ELASTICSEARCH_URL - Elasticsearch endpoint (default: http://localhost:9200)
  ELASTICSEARCH_INDEX - Target index name (default: clawdianshield-events)
  ELASTICSEARCH_USER - Basic auth username (optional, for secured clusters)
  ELASTICSEARCH_PASSWORD - Basic auth password (optional)

Designed for local dev Elasticsearch without TLS. For production, add SSL
verification and proper authentication.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Load environment variables lazily inside functions so .env can be loaded
# after module import
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _get_es_client():
    """
    Get configured Elasticsearch client. Returns None if not configured.
    """
    try:
        from elasticsearch import Elasticsearch
    except ImportError:
        logger.warning("elasticsearch package not installed. Run: pip install elasticsearch")
        return None
    
    es_url = os.getenv("ELASTICSEARCH_URL", "").strip()
    if not es_url:
        return None
    
    es_user = os.getenv("ELASTICSEARCH_USER", "").strip()
    es_password = os.getenv("ELASTICSEARCH_PASSWORD", "").strip()
    
    if es_user and es_password:
        client = Elasticsearch(
            [es_url],
            basic_auth=(es_user, es_password),
            verify_certs=False,  # For local dev; enable for production
            request_timeout=30,
        )
    else:
        client = Elasticsearch(
            [es_url],
            verify_certs=False,
            request_timeout=30,
        )
    
    return client


def read_jsonl_events(jsonl_path: Path) -> list[dict[str, Any]]:
    """
    Read all NormalizedEvent records from a JSONL file.
    Returns a list of dictionaries (parsed JSON objects).
    """
    events: list[dict[str, Any]] = []
    
    if not jsonl_path.exists():
        logger.warning(f"JSONL file not found: {jsonl_path}")
        return events
    
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON at {jsonl_path}:{line_num}: {e}")
    
    logger.info(f"Read {len(events)} events from {jsonl_path}")
    return events


def bulk_ingest(events: list[dict[str, Any]], index_name: str | None = None) -> dict[str, Any]:
    """
    Bulk ingest events into Elasticsearch.
    
    Returns a summary dictionary with:
      - success: bool
      - sent: int (number of events sent)
      - failed: int (number of events that failed)
      - errors: list of error messages
    """
    result = {
        "success": False,
        "sent": 0,
        "failed": 0,
        "errors": [],
    }
    
    if not events:
        result["success"] = True
        return result
    
    client = _get_es_client()
    if not client:
        result["errors"].append("Elasticsearch client not configured (missing ELASTICSEARCH_URL)")
        return result
    
    index = index_name or os.getenv("ELASTICSEARCH_INDEX", "clawdianshield-events")
    
    # Check cluster health
    try:
        if not client.ping():
            result["errors"].append("Elasticsearch cluster is not reachable")
            return result
    except Exception as e:
        result["errors"].append(f"Failed to ping Elasticsearch: {e}")
        return result
    
    try:
        from elasticsearch import helpers
        
        # Use helpers.bulk for more robust bulk ingestion
        actions = [
            {
                "_index": index,
                "_source": event,
            }
            for event in events
        ]
        
        success_count, errors = helpers.bulk(
            client,
            actions,
            refresh=True,  # Make data immediately searchable
            raise_on_error=False,
        )
        
        result["sent"] = success_count
        result["failed"] = len(events) - success_count
        
        if errors:
            result["errors"].extend([str(e) for e in errors[:10]])  # Limit error list
        
        result["success"] = result["failed"] == 0
        
        logger.info(
            f"Bulk ingest complete: {result['sent']} sent, "
            f"{result['failed']} failed to index '{index}'"
        )
        
    except Exception as e:
        result["errors"].append(f"Bulk ingest failed: {e}")
        logger.error(f"Elasticsearch bulk ingest error: {e}")
    
    return result


def ship_evidence_to_elasticsearch(
    evidence_dir: Path | str = "./evidence",
    index_name: str | None = None,
) -> dict[str, Any]:
    """
    Read all JSONL evidence files from evidence_dir and bulk ingest them
    into Elasticsearch.
    
    Returns aggregated results dictionary.
    """
    evidence_path = Path(evidence_dir)
    
    all_events: list[dict[str, Any]] = []
    
    # Read file events
    file_events_path = evidence_path / "file_events.jsonl"
    all_events.extend(read_jsonl_events(file_events_path))
    
    # Read auth events
    auth_events_path = evidence_path / "auth_events.jsonl"
    all_events.extend(read_jsonl_events(auth_events_path))
    
    if not all_events:
        logger.warning("No events found in evidence directory")
        return {
            "success": True,
            "sent": 0,
            "failed": 0,
            "errors": [],
        }
    
    # Bulk ingest all events
    result = bulk_ingest(all_events, index_name)
    
    return result


def create_index_template(index_name: str | None = None) -> bool:
    """
    Create an Elasticsearch index template with proper field mappings for
    NormalizedEvent schema.
    
    Returns True if template was created successfully, False otherwise.
    """
    client = _get_es_client()
    if not client:
        logger.warning("Elasticsearch client not configured")
        return False
    
    index = index_name or os.getenv("ELASTICSEARCH_INDEX", "clawdianshield-events")
    
    # Define index template with field mappings
    template_body = {
        "index_patterns": [f"{index}-*"],
        "template": {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,  # No replicas for local dev
            },
            "mappings": {
                "properties": {
                    "run_id": {"type": "keyword"},
                    "scenario_id": {"type": "keyword"},
                    "host": {"type": "keyword"},
                    "event_type": {"type": "keyword"},
                    "timestamp": {"type": "date"},
                    "severity": {"type": "keyword"},
                    "collector": {"type": "keyword"},
                    "details": {"type": "object", "enabled": True},
                }
            },
        },
    }
    
    try:
        client.indices.put_index_template(
            name=f"{index}-template",
            body=template_body,
        )
        logger.info(f"Created index template: {index}-template")
        return True
    except Exception as e:
        logger.error(f"Failed to create index template: {e}")
        return False


# CLI interface for manual testing
if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )
    
    p = argparse.ArgumentParser(
        description="Ship ClawdianShield evidence JSONL to Elasticsearch",
    )
    p.add_argument(
        "--evidence-dir",
        default="./clawdianshield/evidence",
        help="Path to evidence directory containing JSONL files",
    )
    p.add_argument(
        "--index",
        default=None,
        help="Elasticsearch index name (default: from ELASTICSEARCH_INDEX env var)",
    )
    p.add_argument(
        "--create-template",
        action="store_true",
        help="Create index template before ingesting",
    )
    
    args = p.parse_args()
    
    if args.create_template:
        print("Creating index template...")
        create_index_template(args.index)
    
    print(f"Shipping evidence from {args.evidence_dir} to Elasticsearch...")
    result = ship_evidence_to_elasticsearch(
        evidence_dir=args.evidence_dir,
        index_name=args.index,
    )
    
    print(f"\nResults:")
    print(f"  Success: {result['success']}")
    print(f"  Sent: {result['sent']}")
    print(f"  Failed: {result['failed']}")
    if result["errors"]:
        print(f"  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")
