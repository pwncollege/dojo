#!/usr/bin/env python3
import subprocess
import json
import sys
import os

from utils import DOJO_URL, DOJO_CONTAINER

api_key = os.environ.get('OPENAI_API_KEY')
if not api_key:
    print("OPENAI_API_KEY not set")
    sys.exit(0)

prompt = f"""
You are an expert Quality Assurance tester.
You are known as the Ur-Tester, and have ascended BEYOND mere testing into something approaching an art form.
You have spent your life finding problems in testcases, spotting bugs, and keeping software functional.
Nothing escapes your gaze, and you find all issues.

You also have access to a Playwright MCP server.
Explore the pwn.college website starting at {DOJO_URL} and check for functionality that has been broken by this PR.
The summary of the PR's changes:

{open("diff_summary").read()}

Make a thorough plan for what you want to test.
Think about what user stories might be impacted by this PR, and thoroughly test them.
Throw in some normal functionality for good measure.

TRICKS:
- keep in mind that the dojo is a multi-docker infra running inside the {DOJO_CONTAINER} docker-in-docker container.
- feel free to "cheat": you can `docker exec {DOJO_CONTAINER} docker exec $WHATEVER` directly into containers to look around
- `docker exec {DOJO_CONTAINER} dojo enter -s $USER` is especially useful for getting flags without having to solve the actual tricky challenges, to test that part of the dojo's functionality
- this environment is disposable for your use; don't worry about breaking things

IMPORTANT: 
- Focus ONLY on actual broken functionality, not design preferences
- Actually use the dojo, don't just navigate around.

After exploration, return a JSON report:
{{
    "pass": true/false (false if any critical issues found),
    "pages_explored": ["list of URLs visited"],
    "issues_found": [
        {{
            "page": "URL where issue was found",
            "issue": "Description of what's broken",
            "severity": "critical|major|minor"
        }}
    ],
    "summary": "Brief summary of site health"
}}

Be thorough but focus on ACTUAL BREAKAGE. Empty pages, missing descriptions, etc are OK if intentional. Bad design is OK. Only fail for things that literally don't work.
"""

cmd = [
    "npx", "--yes", "@openai/codex",
    "exec",
    "--config", 'mcp_servers.playwright.command="npx"',
    "--config", 'mcp_servers.playwright.args=["--yes", "@playwright/mcp@0.0.32", "--browser", "firefox", "--headless"]',
    "--full-auto", "--skip-git-repo-check",
    prompt
]

env = os.environ.copy()
env['OPENAI_API_KEY'] = api_key

result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    #timeout=120,  # 2 minute timeout
    env=env
)

if result.returncode != 0:
    raise RuntimeError(f"GPT exploration failed: {result.stderr}")

exploration_result = result.stdout
    
# Try to extract JSON from the response
try:
    # Look for JSON in the response (GPT might include other text)
    json_start = exploration_result.find('{')
    json_end = exploration_result.rfind('}') + 1
    if json_start >= 0 and json_end > json_start:
        json_str = exploration_result[json_start:json_end]
        report = json.loads(json_str)
    else:
        # Try to parse the whole thing as JSON
        report = json.loads(exploration_result)
    
    print("\n=== Exploration Report ===")
    print(f"Result: {'PASS' if report['pass'] else 'FAIL'}")
    print(f"Pages explored: {len(report.get('pages_explored', []))}")
    for page in report.get('pages_explored', []):
        print(f"  - {page}")
    
    if report.get('issues_found'):
        print(f"\nIssues found: {len(report['issues_found'])}")
        for issue in report['issues_found']:
            severity = issue.get('severity', 'unknown')
            print(f"  [{severity.upper()}] {issue['page']}")
            print(f"    {issue['issue']}")
    else:
        print("\nNo issues found!")
    
    print(f"\nSummary: {report.get('summary', 'No summary provided')}")
    
    # Assert based on pass/fail
    if not report['pass']:
        critical_issues = [i for i in report.get('issues_found', []) 
                         if i.get('severity') == 'critical']
        if critical_issues:
            issue_list = '; '.join([i['issue'] for i in critical_issues])
            print(f"Critical functionality issues found: {issue_list}")
            sys.exit(1)
        else:
            issue_list = '; '.join([i['issue'] for i in report.get('issues_found', [])])
            print(f"Functionality issues found: {issue_list}")
            sys.exit(1)
    
except json.JSONDecodeError:
    print(f"\n=== Raw GPT Response ===")
    print(exploration_result)
    # Don't fail the test if GPT's response isn't valid JSON
    # This might mean the exploration itself had issues
    print("\nWarning: Could not parse GPT's JSON response. Site might be OK, or GPT had issues exploring.")
    sys.exit(1)
except Exception as e:
    print(f"\nError during exploration: {e}")
    print(f"Site exploration failed: {e}")
    sys.exit(1)
