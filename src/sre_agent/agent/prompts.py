"""Prompts and message templates for the agent."""

REPORT_HEADER = """
# SRE Agent Report
"""

REPORT_SECTION_DETECTION = """
## What went wrong
{summary}

**Root cause:** {root_cause}

**Evidence:**
{evidence}
"""

REPORT_SECTION_ACTIONS = """
## Actions taken
{actions}
"""

REPORT_SECTION_VERIFICATION = """
## Verification
{verification}
"""

REPORT_NO_ISSUE = """
## Result
No operational issue was detected in the cluster. All pods appear to be running and ready.
"""

REPORT_DRY_RUN = """
(Dry run: no remediation was applied.)
"""
