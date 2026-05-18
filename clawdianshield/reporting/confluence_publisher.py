"""
reporting/confluence_publisher.py

Aggregates ClawdianShield run reports and evidence into HTML reports, then
optionally publishes them to Confluence via the REST API.

Env vars:
  CONFLUENCE_URL - Confluence instance URL (e.g., https://your-domain.atlassian.net)
  CONFLUENCE_USER - Username or email for basic auth
  CONFLUENCE_API_TOKEN - API token (not password) for Confluence Cloud
  CONFLUENCE_SPACE_KEY - Space key where reports will be published
  CONFLUENCE_PARENT_PAGE_ID - Optional parent page ID for organizing reports

For Confluence Cloud, generate an API token at:
https://id.atlassian.com/manage-profile/security/api-tokens
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def read_run_report(run_id: str, reports_dir: Path | str = "./reports") -> dict[str, Any] | None:
    """
    Read the exec_log JSON for a given run_id.
    Returns the parsed JSON or None if not found.
    """
    reports_path = Path(reports_dir)
    exec_log_path = reports_path / f"{run_id}_exec_log.json"
    
    if not exec_log_path.exists():
        logger.warning(f"Exec log not found: {exec_log_path}")
        return None
    
    try:
        with open(exec_log_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {exec_log_path}: {e}")
        return None


def read_run_brief(run_id: str, reports_dir: Path | str = "./reports") -> dict[str, Any] | None:
    """
    Read the AI-generated brief JSON for a given run_id.
    Returns the parsed JSON or None if not found.
    """
    reports_path = Path(reports_dir)
    brief_path = reports_path / f"{run_id}_brief.json"
    
    if not brief_path.exists():
        return None
    
    try:
        with open(brief_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {brief_path}: {e}")
        return None


def read_evidence_events(
    run_id: str,
    evidence_dir: Path | str = "./evidence",
) -> list[dict[str, Any]]:
    """
    Read all JSONL evidence events matching the given run_id.
    Returns a list of parsed event dictionaries.
    """
    evidence_path = Path(evidence_dir)
    events: list[dict[str, Any]] = []
    
    # Read file events
    file_events_path = evidence_path / "file_events.jsonl"
    if file_events_path.exists():
        with open(file_events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("run_id") == run_id:
                        events.append(event)
                except json.JSONDecodeError:
                    pass
    
    # Read auth events
    auth_events_path = evidence_path / "auth_events.jsonl"
    if auth_events_path.exists():
        with open(auth_events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("run_id") == run_id:
                        events.append(event)
                except json.JSONDecodeError:
                    pass
    
    # Sort by timestamp
    events.sort(key=lambda e: e.get("timestamp", ""))
    
    logger.info(f"Read {len(events)} evidence events for run {run_id}")
    return events


def generate_html_report(
    run_id: str,
    reports_dir: Path | str = "./reports",
    evidence_dir: Path | str = "./evidence",
) -> str:
    """
    Generate a comprehensive HTML report for a ClawdianShield run.
    
    Aggregates:
      - Exec log (scenario metadata, steps, status)
      - AI brief (if available)
      - Evidence events (file and auth events)
    
    Returns the HTML string.
    """
    run_report = read_run_report(run_id, reports_dir)
    if not run_report:
        return f"<html><body><h1>Report Not Found</h1><p>No exec log found for run_id: {run_id}</p></body></html>"
    
    brief = read_run_brief(run_id, reports_dir)
    events = read_evidence_events(run_id, evidence_dir)
    
    # Extract key metadata
    scenario_name = run_report.get("scenario_name", "Unknown Scenario")
    scenario_id = run_report.get("scenario_id", run_id)
    status = run_report.get("status", "unknown")
    started_at = run_report.get("started_at", "")
    completed_at = run_report.get("completed_at", "")
    
    steps = run_report.get("steps", [])
    step_count = len(steps)
    failed_steps = [s for s in steps if s.get("status") == "failed"]
    failed_count = len(failed_steps)
    
    coverage = run_report.get("telemetry_coverage", {})
    gaps = run_report.get("coverage_gaps", [])
    
    # Build HTML
    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        f"<title>ClawdianShield Report - {scenario_name}</title>",
        "<style>",
        "body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; background: #f5f5f5; }",
        ".container { max-width: 1200px; margin: 0 auto; background: white; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }",
        "h1 { color: #d32f2f; border-bottom: 3px solid #d32f2f; padding-bottom: 10px; }",
        "h2 { color: #1976d2; margin-top: 30px; border-bottom: 2px solid #1976d2; padding-bottom: 8px; }",
        "h3 { color: #455a64; margin-top: 20px; }",
        ".metadata { background: #e3f2fd; padding: 15px; border-radius: 4px; margin: 20px 0; }",
        ".metadata p { margin: 5px 0; }",
        ".status { display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; }",
        ".status.completed { background: #4caf50; color: white; }",
        ".status.failed { background: #f44336; color: white; }",
        ".status.completed_with_failures { background: #ff9800; color: white; }",
        "table { width: 100%; border-collapse: collapse; margin: 20px 0; }",
        "th { background: #37474f; color: white; padding: 12px; text-align: left; }",
        "td { padding: 10px; border-bottom: 1px solid #ddd; }",
        "tr:hover { background: #f5f5f5; }",
        ".step-failed { background: #ffebee; }",
        ".severity-critical { color: #d32f2f; font-weight: bold; }",
        ".severity-high { color: #f57c00; font-weight: bold; }",
        ".severity-medium { color: #fbc02d; font-weight: bold; }",
        ".severity-info { color: #757575; }",
        ".brief { background: #fff3e0; padding: 20px; border-left: 4px solid #ff9800; margin: 20px 0; }",
        ".brief pre { background: white; padding: 15px; overflow-x: auto; border-radius: 4px; }",
        ".gap { background: #ffcdd2; padding: 8px 12px; margin: 5px 0; border-radius: 4px; }",
        "code { background: #eceff1; padding: 2px 6px; border-radius: 3px; font-family: 'Courier New', monospace; }",
        ".event-details { font-size: 0.9em; color: #666; }",
        "</style>",
        "</head>",
        "<body>",
        "<div class='container'>",
        "<h1>🛡️ ClawdianShield Execution Report</h1>",
        f"<h2>{scenario_name}</h2>",
        
        # Metadata section
        "<div class='metadata'>",
        f"<p><strong>Run ID:</strong> <code>{run_id}</code></p>",
        f"<p><strong>Scenario ID:</strong> <code>{scenario_id}</code></p>",
        f"<p><strong>Status:</strong> <span class='status {status}'>{status.upper()}</span></p>",
        f"<p><strong>Started:</strong> {started_at}</p>",
        f"<p><strong>Completed:</strong> {completed_at}</p>",
        f"<p><strong>Total Steps:</strong> {step_count} ({failed_count} failed)</p>",
        f"<p><strong>Evidence Events:</strong> {len(events)}</p>",
        "</div>",
    ]
    
    # AI Brief section (if available)
    if brief:
        brief_markdown = brief.get("brief_markdown", "")
        model = brief.get("model", "unknown")
        html_parts.extend([
            "<h2>🤖 AI Intelligence Brief</h2>",
            "<div class='brief'>",
            f"<p><strong>Generated by:</strong> {model}</p>",
            "<pre>" + _escape_html(brief_markdown) + "</pre>",
            "</div>",
        ])
    
    # Coverage Gaps section
    if gaps:
        html_parts.extend([
            "<h2>⚠️ Coverage Gaps</h2>",
            "<p>The following expected telemetry was not observed:</p>",
        ])
        for gap in gaps:
            html_parts.append(f"<div class='gap'>{_escape_html(str(gap))}</div>")
    
    # Telemetry Coverage section
    html_parts.extend([
        "<h2>📊 Telemetry Coverage</h2>",
        "<table>",
        "<tr><th>Event Type</th><th>Expected</th><th>Produced By</th></tr>",
    ])
    
    for event_type, details in coverage.items():
        expected = details.get("expected", False)
        produced_by = details.get("produced_by", [])
        produced_by_str = ", ".join(produced_by) if produced_by else "N/A"
        html_parts.append(
            f"<tr><td><code>{event_type}</code></td><td>{expected}</td><td>{produced_by_str}</td></tr>"
        )
    
    html_parts.append("</table>")
    
    # Execution Steps section
    html_parts.extend([
        "<h2>📝 Execution Steps</h2>",
        "<table>",
        "<tr><th>Behavior</th><th>Step ID</th><th>Status</th><th>Elapsed (s)</th><th>Command</th></tr>",
    ])
    
    for step in steps:
        behavior = step.get("behavior", "")
        step_id = step.get("step_id", "")
        step_status = step.get("status", "unknown")
        elapsed = step.get("elapsed_s", 0.0)
        command = step.get("command", "")[:120]  # Truncate long commands
        
        row_class = "step-failed" if step_status == "failed" else ""
        
        html_parts.append(
            f"<tr class='{row_class}'>"
            f"<td>{_escape_html(behavior)}</td>"
            f"<td><code>{_escape_html(step_id)}</code></td>"
            f"<td>{_escape_html(step_status)}</td>"
            f"<td>{elapsed:.3f}</td>"
            f"<td><code>{_escape_html(command)}</code></td>"
            "</tr>"
        )
    
    html_parts.append("</table>")
    
    # Evidence Events section
    if events:
        html_parts.extend([
            "<h2>🔍 Evidence Events</h2>",
            "<table>",
            "<tr><th>Timestamp</th><th>Host</th><th>Type</th><th>Severity</th><th>Details</th></tr>",
        ])
        
        # Show first 50 events (prevent huge HTML for long runs)
        displayed_events = events[:50]
        
        for event in displayed_events:
            timestamp = event.get("timestamp", "")[:19]  # Trim microseconds
            host = event.get("host", "")
            event_type = event.get("event_type", "")
            severity = event.get("severity", "info")
            details = event.get("details", {})
            
            # Format details as compact JSON
            details_str = json.dumps(details, separators=(",", ":"))[:150]
            
            html_parts.append(
                f"<tr>"
                f"<td>{_escape_html(timestamp)}</td>"
                f"<td>{_escape_html(host)}</td>"
                f"<td><code>{_escape_html(event_type)}</code></td>"
                f"<td class='severity-{severity}'>{_escape_html(severity)}</td>"
                f"<td class='event-details'>{_escape_html(details_str)}</td>"
                "</tr>"
            )
        
        html_parts.append("</table>")
        
        if len(events) > 50:
            html_parts.append(f"<p><em>Showing first 50 of {len(events)} total events.</em></p>")
    
    # Footer
    html_parts.extend([
        "<hr style='margin-top: 40px; border: none; border-top: 1px solid #ccc;'>",
        f"<p style='text-align: center; color: #999;'>Generated by ClawdianShield at {datetime.now(timezone.utc).isoformat()}</p>",
        "</div>",
        "</body>",
        "</html>",
    ])
    
    return "\n".join(html_parts)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def publish_to_confluence(
    html_content: str,
    page_title: str,
    space_key: str | None = None,
    parent_page_id: str | None = None,
) -> dict[str, Any]:
    """
    Publish an HTML report to Confluence.
    
    Returns a result dictionary with:
      - success: bool
      - page_id: str (Confluence page ID if successful)
      - page_url: str (Web URL to the published page)
      - error: str (error message if failed)
    """
    result: dict[str, Any] = {
        "success": False,
        "page_id": None,
        "page_url": None,
        "error": None,
    }
    
    # Read Confluence config from environment
    confluence_url = os.getenv("CONFLUENCE_URL", "").strip().rstrip("/")
    confluence_user = os.getenv("CONFLUENCE_USER", "").strip()
    confluence_token = os.getenv("CONFLUENCE_API_TOKEN", "").strip()
    space = space_key or os.getenv("CONFLUENCE_SPACE_KEY", "").strip()
    parent_id = parent_page_id or os.getenv("CONFLUENCE_PARENT_PAGE_ID", "").strip()
    
    if not confluence_url or not confluence_user or not confluence_token or not space:
        result["error"] = (
            "Confluence not configured. Set CONFLUENCE_URL, CONFLUENCE_USER, "
            "CONFLUENCE_API_TOKEN, and CONFLUENCE_SPACE_KEY in .env"
        )
        return result
    
    try:
        from atlassian import Confluence
    except ImportError:
        result["error"] = (
            "atlassian-python-api package not installed. "
            "Run: pip install atlassian-python-api"
        )
        return result
    
    try:
        # Initialize Confluence client
        confluence = Confluence(
            url=confluence_url,
            username=confluence_user,
            password=confluence_token,  # API token, not actual password
            cloud=True,  # Use cloud API endpoints
        )
        
        # Check if page already exists
        existing_page = confluence.get_page_by_title(space=space, title=page_title)
        
        if existing_page:
            # Update existing page
            page_id = existing_page["id"]
            confluence.update_page(
                page_id=page_id,
                title=page_title,
                body=html_content,
                type="page",
                representation="storage",  # Confluence storage format
            )
            logger.info(f"Updated existing Confluence page: {page_id}")
        else:
            # Create new page
            new_page = confluence.create_page(
                space=space,
                title=page_title,
                body=html_content,
                parent_id=parent_id if parent_id else None,
                type="page",
                representation="storage",
            )
            page_id = new_page["id"]
            logger.info(f"Created new Confluence page: {page_id}")
        
        # Build page URL
        page_url = f"{confluence_url}/wiki/spaces/{space}/pages/{page_id}"
        
        result["success"] = True
        result["page_id"] = page_id
        result["page_url"] = page_url
        
    except Exception as e:
        result["error"] = f"Confluence API error: {e}"
        logger.error(result["error"])
    
    return result


def generate_and_publish_report(
    run_id: str,
    reports_dir: Path | str = "./reports",
    evidence_dir: Path | str = "./evidence",
    publish: bool = False,
) -> dict[str, Any]:
    """
    Generate an HTML report for a run and optionally publish it to Confluence.
    
    Returns a result dictionary with:
      - html_path: Path to saved HTML file
      - confluence: dict with Confluence publish results (if publish=True)
    """
    # Generate HTML
    html_content = generate_html_report(run_id, reports_dir, evidence_dir)
    
    # Save HTML locally
    reports_path = Path(reports_dir)
    html_path = reports_path / f"{run_id}_report.html"
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    logger.info(f"HTML report saved to {html_path}")
    
    result: dict[str, Any] = {
        "html_path": str(html_path),
    }
    
    # Publish to Confluence if requested
    if publish:
        run_report = read_run_report(run_id, reports_dir)
        scenario_name = run_report.get("scenario_name", "Unknown Scenario") if run_report else "Report"
        page_title = f"ClawdianShield - {scenario_name} - {run_id}"
        
        confluence_result = publish_to_confluence(
            html_content=html_content,
            page_title=page_title,
        )
        
        result["confluence"] = confluence_result
    
    return result


# CLI interface
if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )
    
    p = argparse.ArgumentParser(
        description="Generate and publish ClawdianShield HTML reports",
    )
    p.add_argument(
        "run_id",
        help="Run ID to generate report for",
    )
    p.add_argument(
        "--reports-dir",
        default="./clawdianshield/reports",
        help="Path to reports directory",
    )
    p.add_argument(
        "--evidence-dir",
        default="./clawdianshield/evidence",
        help="Path to evidence directory",
    )
    p.add_argument(
        "--publish",
        action="store_true",
        help="Publish report to Confluence",
    )
    
    args = p.parse_args()
    
    print(f"Generating HTML report for run {args.run_id}...")
    result = generate_and_publish_report(
        run_id=args.run_id,
        reports_dir=args.reports_dir,
        evidence_dir=args.evidence_dir,
        publish=args.publish,
    )
    
    print(f"\nHTML report saved to: {result['html_path']}")
    
    if "confluence" in result:
        conf = result["confluence"]
        if conf["success"]:
            print(f"✅ Published to Confluence: {conf['page_url']}")
        else:
            print(f"❌ Confluence publish failed: {conf['error']}")
