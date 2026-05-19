#!/usr/bin/env python3
"""Create Blocked-by links between dependent Jira issues."""
import os, sys, json, requests
from dotenv import load_dotenv

env_path = "/Users/dongliang/.config/opencode/skills/jira-mcp-ops/env/.env"
load_dotenv(dotenv_path=env_path)

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

def link_issues(inward_key, outward_key, link_type="Blocks"):
    """Create link: outward_key link_type inward_key.
    Blocks: ITRADE-153 Blocks ITRADE-159 means 159 is blocked by 153.
    """
    url = f"{JIRA_URL}/rest/api/3/issueLink"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {
        "type": {"name": link_type},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key}
    }
    r = requests.post(url, headers=headers, auth=auth, json=payload)
    if r.status_code == 201:
        print(f"  {outward_key} {link_type} {inward_key}")
        return True
    else:
        print(f"  FAILED: {outward_key} {link_type} {inward_key} - {r.status_code}: {r.text[:200]}")
        return False

# Dependency map: (blocked_issue, blocking_issue)
# Phase 1: ITRADE-169 Delete dead files, ITRADE-170 Relocate scripts, ITRADE-171 Archive legacy
# Phase 2: ITRADE-172 Split feature.py, ITRADE-173 Split html_renderer, ITRADE-174 Consolidate scanner
#          ITRADE-175 Extract Streamlit theme, ITRADE-176 Consolidate verify, ITRADE-177 Decouple dashboard
#          ITRADE-178 Simplify imap_api legacy
# Phase 3: ITRADE-179 Scripts reorg, ITRADE-180 Consolidate Streamlit apps, ITRADE-181 Split pattern_analyzer
#          ITRADE-182 Split pattern_fetcher, ITRADE-183 Split altair.py
dependencies = [
    # Phase 2 blocked by Phase 1
    ("ITRADE-175", "ITRADE-169"),  # Streamlit theme blocked by dead file cleanup
    ("ITRADE-175", "ITRADE-170"),  # Streamlit theme blocked by script relocation
    ("ITRADE-176", "ITRADE-170"),  # Verify consolidation blocked by test relocation
    ("ITRADE-177", "ITRADE-173"),  # Dashboard decouple blocked by html_renderer split
    ("ITRADE-178", "ITRADE-171"),  # imap_api legacy blocked by legacy code archive

    # Phase 3 blocked by Phase 2
    ("ITRADE-179", "ITRADE-176"),  # Scripts reorg blocked by verify consolidation
    ("ITRADE-179", "ITRADE-170"),  # Scripts reorg blocked by test relocation
    ("ITRADE-180", "ITRADE-175"),  # Streamlit consolidation blocked by shared theme
    ("ITRADE-180", "ITRADE-173"),  # Streamlit consolidation blocked by html_renderer split
]

print("Creating issue links...")
created = 0
for blocked, blocking in dependencies:
    if link_issues(blocked, blocking, "Blocks"):
        created += 1

print(f"\nCreated {created}/{len(dependencies)} links")
