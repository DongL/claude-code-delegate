#!/usr/bin/env python3
"""Batch create ITRADE architecture reorganization issues."""
import os, sys, json, requests
from dotenv import load_dotenv

env_path = "/Users/dongliang/.config/opencode/skills/jira-mcp-ops/env/.env"
load_dotenv(dotenv_path=env_path)

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

if not JIRA_URL or not JIRA_EMAIL or not JIRA_API_TOKEN:
    print("Error: Jira environment variables not set.")
    sys.exit(1)

def create_issue(project, summary, description, issue_type="Task", labels=None, priority="Medium"):
    url = f"{JIRA_URL}/rest/api/3/issue"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    fields = {
        "project": {"key": project},
        "summary": summary,
        "issuetype": {"name": issue_type},
        "priority": {"name": priority},
        "labels": labels or [],
        "description": {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
        }
    }

    response = requests.post(url, headers=headers, auth=auth, json={"fields": fields})
    if response.status_code == 201:
        data = response.json()
        print(f"Created {data['key']}: {summary}")
        return data['key']
    else:
        print(f"FAILED to create '{summary}'. Status: {response.status_code}")
        print(response.text[:500])
        return None

# Define all issues
issues = [
    {
        "summary": "Delete dead files and backup artifacts",
        "priority": "High",
        "hitl": False,
        "description": """h3. Context
Refactoring report identified 12+ dead code files and 9 empty (0-byte) files.

h3. Actions
* Delete 9 empty files in scripts/: debug_dashboard_startup.py, debug_hanging_method.py, debug_minimal_import.py, debug_paths.py, debug_real_dashboard.py, direct_scan_market.py, launch_dashboard.py, launch_modern_dashboard.py, launch_simple_dashboard.py
* Delete backup files: dashboard/my_dashboard.py.bak, app/scanner_original_backup.py, streamlit_apps/market_dashboard/main.py.backup
* Delete providers/real_chinese_data.py (superseded by real_chinese_data_refactored.py)

h3. Success Criteria
* No .bak files in repo
* No 0-byte .py files in scripts/
* Only real_chinese_data_refactored.py exists in providers/
* make test passes"""
    },
    {
        "summary": "Relocate misplaced scripts (test_*.py to tests/, health scripts out)",
        "priority": "High",
        "hitl": False,
        "description": """h3. Context
15+ test_*.py files found in scripts/ that belong in tests/. Health/ops shell scripts (*.sh) mixed with analysis scripts.

h3. Actions
* Move test_*.py files from scripts/ to tests/: test_0002_hk.py, test_1810_hk.py, test_1810_hk_fix.py, test_1810_hk_validation.py, test_ab_pattern_fix.py, test_all_chinese_symbols.py, test_all_portfolio_symbols.py, test_chinese_backup.py, test_chinese_backup_simple.py, test_hk_stocks_direct.py, test_hk_stocks_hang.py, test_relaxed_validation.py, test_staleness_warning.py, test_yfinance_fallback.py
* Move shell scripts to ops/: login.sh, start_server.sh, stop_server.sh, restart_server.sh, status.sh, kill_scanner_processes.sh, ralph_agent_stub.sh
* Move dashboard_server.py to ops/ or dashboard/

h3. Success Criteria
* No test_*.py files in scripts/ root
* No .sh files in scripts/ root
* All tests discoverable by pytest in tests/
* make test passes"""
    },
    {
        "summary": "Archive legacy code (app/legacy/, app/shiny_app_related/)",
        "priority": "High",
        "hitl": False,
        "description": """h3. Context
app/legacy/ contains superseded scanner and plotting code. app/shiny_app_related/ contains an unused Shiny (R) app attempt.

h3. Actions
* Move app/legacy/pattern_plotting.py and app/legacy/scanner_backlog.py to app/legacy/ (already there) - verify no active imports, then delete or mark deprecated
* Move app/shiny_app_related/app.py and app/shiny_app_related/server.py to app/shiny_app_related/ (already there) - verify no active imports, then delete or archive
* Search codebase for any imports from these directories before deletion
* If any active imports exist, add deprecation warnings instead of deleting

h3. Success Criteria
* No active imports from app/legacy/ or app/shiny_app_related/
* Either directories removed or all files marked with deprecation warnings
* make test passes"""
    },
    {
        "summary": "Split feature.py (1582 lines) into indicators.py + facade",
        "priority": "High",
        "hitl": True,
        "description": """h3. Context
pattern_analysis/feature.py is the single largest file at 1,582 lines. Contains FeatureConfig, FeatureProcessor, FeatureValidator, FeaturePipeline, and Feature classes.

h3. Proposed Split
* feature_config.py - FeatureConfig class and configuration logic
* feature_processor.py - FeatureProcessor class
* feature_validator.py - FeatureValidator class
* feature_pipeline.py - FeaturePipeline class
* feature.py - Facade that re-exports from sub-modules for backward compatibility

h3. Design Decisions (HITL)
* Should FeatureValidator be merged into FeatureProcessor?
* Should feature_pipeline.py depend on processor or validator first?
* What is the canonical import path after split?

h3. Success Criteria
* Each new file < 500 lines
* from itrade_imap.pattern_analysis.feature import FeatureConfig, FeatureProcessor, FeatureValidator, FeaturePipeline, Feature works unchanged
* make test passes"""
    },
    {
        "summary": "Split html_renderer.py (extract JS/CSS templates)",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
dashboard/html_renderer.py is 1,137 lines. Contains file resolution, HTTP server, HTML generation, and browser launching logic.

h3. Proposed Split
* file_resolver.py - Template file resolution logic
* http_server.py - HTTP server for serving HTML
* html_generator.py - HTML generation core
* browser_launcher.py - Browser launch logic
* html_renderer.py - Facade

h3. Design Decisions (HITL)
* Should JS/CSS templates be extracted to separate template files?
* Should http_server.py remain in dashboard/ or move to a server package?
* What is the minimum viable facade?

h3. Success Criteria
* html_renderer.py facade < 100 lines
* Each module < 400 lines
* Dashboard HTML output is byte-identical for same inputs
* make test passes"""
    },
    {
        "summary": "Consolidate scanner cores",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
Scanner logic spread across app/scanner/core.py, pattern_analysis/pattern_analyzer.py, and multiple scripts. Need to consolidate into a single scanner core.

h3. Actions
* Analyze current scanner flow: app/scanner/core.py (Prefect-integrated) vs pattern_analysis/pattern_analyzer.py
* Identify duplicated scanning logic
* Consolidate into app/scanner/ with clear module boundaries
* Update all script imports to use canonical scanner path

h3. Design Decisions (HITL)
* Should pattern_analyzer.py scanning methods move to app/scanner/?
* How to handle Prefect integration - keep in app/scanner/ or extract?
* What is the scanner's public API?

h3. Success Criteria
* Single entry point for market scanning
* No duplicated scan logic
* make scan-market produces same output
* make test passes"""
    },
    {
        "summary": "Extract shared Streamlit theme",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
4 Streamlit apps each have their own config/app_config.py with overlapping settings (theme, proxy, data paths). Color schemes, styling, and layout patterns repeated.

h3. Actions
* Create streamlit_apps/components/theme.py with unified dark theme config
* Create streamlit_apps/components/selectors.py with shared symbol/period selectors
* Create streamlit_apps/components/charts.py with shared chart rendering
* Create streamlit_apps/config/app_config.py with unified configuration
* Update each app to import from shared components

h3. Design Decisions (HITL)
* Should theme be a dataclass or dict-based config?
* How to handle app-specific theme overrides?
* Should components be a proper Python package or Streamlit-style imports?

h3. Success Criteria
* All 4 apps use shared theme config
* No duplicated color scheme definitions
* Each app still launches independently
* Visual output unchanged"""
    },
    {
        "summary": "Consolidate verify scripts",
        "priority": "Medium",
        "hitl": False,
        "description": """h3. Context
7 verify_*.py files in scripts/ that either should be converted to proper tests or consolidated.

h3. Actions
* Review each verify script: verify_dashboard_fix.py, verify_fix.py, verify_tests.py, verify_stocks_fix*.py (2), verify_option_pipeline.py, verify_reorganization.py
* Convert verification logic to pytest tests in tests/
* Delete verify scripts that are redundant with proper tests
* Move any one-time verification scripts to scripts/debugging/ with documentation

h3. Success Criteria
* All verification logic covered by pytest tests
* No verify_*.py files in scripts/ root
* make test covers all previous verify script checks"""
    },
    {
        "summary": "Decouple dashboard data model",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
dashboard/my_dashboard.py (1,091 lines) mixes data model logic with UI interface. Dashboard plotting modularity has inconsistent protocol enforcement.

h3. Actions
* Extract dashboard data models to dashboard/models.py
* Create dashboard_interface.py with clean DashboardInterface protocol
* Enforce PlotRenderer protocol in dashboard/plotting/
* Add registry pattern for plot type -> renderer mapping

h3. Design Decisions (HITL)
* Should models.py use dataclasses or Pydantic?
* What is the minimal DashboardInterface?
* Should plotting registry use decorators or explicit registration?

h3. Success Criteria
* my_dashboard.py reduced to < 400 lines (facade + interface)
* models.py contains all data structures
* New plot types can be added without modifying existing code
* Dashboard renders identical output"""
    },
    {
        "summary": "Simplify imap_api legacy (HITL)",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
imap_api/ contains legacy services/, commands/, executors/ directories maintained for backward compatibility but not used by primary scanner flow.

h3. Proposed Changes
* Create imap_api/r_bridge.py - extract rpy2 executor logic
* Move services/, commands/, executors/, Rimap.py to imap_api/legacy/
* Update pattern_scanner.py to import from r_bridge.py
* Add re-export __init__.py in old paths with deprecation warnings
* Add DeprecationWarning to legacy imports

h3. Design Decisions (HITL)
* Should r_bridge.py handle mock fallback or leave it to pattern_scanner?
* How long to keep legacy re-exports?
* Should SERVICES_AVAILABLE check R at module load or lazily?

h3. Success Criteria
* from itrade_imap.imap_api import PatternScanner, ScanConfig works unchanged
* from itrade_imap.imap_api import SERVICES_AVAILABLE works unchanged
* Legacy imports work with DeprecationWarning
* No change in runtime behavior
* make test passes"""
    },
    {
        "summary": "Scripts reorganization (HITL)",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
~158 files in scripts/ with no categorization. Mix of analysis tools, debug helpers, publishing scripts, dashboard launchers, and test utilities.

h3. Target Structure
* scripts/analysis/ - Market analysis & scanning (~15 files)
* scripts/dashboard/ - Dashboard launchers & servers (~8 files)
* scripts/ml/ - Model pipeline & Feast (~6 files)
* scripts/publishing/ - Social media publishing (~8 files)
* scripts/data/ - Data inspection & migration (~6 files)
* scripts/debugging/ - Debug helpers (~12 files)
* scripts/ops/ - Operations & process management (~6 files)
* scripts/mcp/ - MCP tool integrations (~3 files)
* scripts/finance/ - Finance-specific tools (~5 files)
* scripts/README.md - Index of all scripts

h3. Design Decisions (HITL)
* Should test_*.py that are integration smoke tests stay in scripts/debugging/ or move to tests/?
* Should regenerate_pattern_ids.py become a module function instead of a script?
* How to handle CI scripts that reference old paths?

h3. Success Criteria
* All scripts categorized into subdirectories
* scripts/README.md documents all scripts with usage
* make test passes
* All scripts still runnable from new paths
* CI updated for new paths"""
    },
    {
        "summary": "Consolidate 4 Streamlit apps into multi-page app",
        "priority": "Medium",
        "hitl": True,
        "description": """h3. Context
4 separate Streamlit apps (market_dashboard, option_analyzer, leap_dashboard, purchase_dashboard) with duplicated config, components, and theme logic. Plus 3 root-level server files.

h3. Target Structure
* streamlit_apps/main.py - Single entry point with sidebar navigation
* streamlit_apps/pages/ - Streamlit multi-page convention
* streamlit_apps/components/ - Shared UI components
* streamlit_apps/config/app_config.py - Unified config
* streamlit_apps/assets/style.css - Unified CSS

h3. Migration Steps
1. Create main.py with sidebar navigation
2. Move each app's main.py into pages/N_Name.py
3. Extract duplicated components into components/
4. Unify theme and config
5. Keep old launch paths working as symlinks during transition
6. Remove legacy server files

h3. Design Decisions (HITL)
* How to isolate session state between pages?
* Should pages lazy-load heavy components?
* What is the transition timeline for symlinks?

h3. Success Criteria
* Single deployable Streamlit app
* Each page works independently
* Shared components used by all pages
* Old launch paths still work via symlinks (Phase 1)"""
    },
    {
        "summary": "Split pattern_analyzer.py (1247 lines)",
        "priority": "High",
        "hitl": False,
        "description": """h3. Context
pattern_analysis/pattern_analyzer.py is 1,247 lines. Contains price retrieval, pattern metrics computation, and core analysis logic.

h3. Proposed Split
* price_getter.py - Price data retrieval
* pattern_metrics.py - Pattern metrics computation
* pattern_analyzer_core.py - Core analysis logic
* pattern_analyzer.py - Facade

h3. Success Criteria
* Each new file < 500 lines
* Backward compatible imports
* make test passes"""
    },
    {
        "summary": "Split pattern_fetcher.py (1015 lines)",
        "priority": "Medium",
        "hitl": False,
        "description": """h3. Context
pattern_analysis/pattern_fetcher.py is 1,015 lines. Contains yfinance fetching, pattern ID generation, and data processing.

h3. Proposed Split
* yfinance_fetcher.py - yfinance data fetching
* pattern_id.py - Pattern ID generation
* pattern_processor.py - Data processing
* pattern_fetcher.py - Facade

h3. Success Criteria
* Each new file < 400 lines
* Backward compatible imports
* make test passes"""
    },
    {
        "summary": "Split altair.py plotting (958 lines)",
        "priority": "Medium",
        "hitl": False,
        "description": """h3. Context
option_analysis/plotting/altair.py is 958 lines. Contains chart definitions, metrics computation, and styling.

h3. Proposed Split
* altair_charts.py - Chart definitions
* altair_metrics.py - Metrics computation
* altair_styling.py - Styling logic

h3. Success Criteria
* Each new file < 400 lines
* Backward compatible imports
* Option analysis tests pass"""
    },
]

created = []
for i, issue in enumerate(issues, 1):
    labels = ["needs-triage", "architecture-reorg"]
    if issue["hitl"]:
        labels.append("hitl")
    key = create_issue(
        project="ITRADE",
        summary=f"[Phase 1] {issue['summary']}" if i <= 3 else f"[Phase 2] {issue['summary']}" if i <= 10 else f"[Phase 3] {issue['summary']}",
        description=issue["description"],
        issue_type="Task",
        labels=labels,
        priority=issue["priority"]
    )
    if key:
        created.append(key)

print(f"\n=== Created {len(created)} issues ===")
for k in created:
    print(k)
