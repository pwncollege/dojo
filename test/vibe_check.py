#!/usr/bin/env python3
import subprocess
import json
import sys
import os

from utils import DOJO_URL, DOJO_CONTAINER

api_key = os.environ.get('OPENAI_API_KEY')

if not api_key:
    print("::warning::OPENAI_API_KEY not set - skipping vibe check")
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
Think about what specific user stories might be impacted by this PR, and thoroughly test them.
Look for the intent of the PR and test that the user experience changes according to the PR's intent.
Make sure nothing breaks along the way.
Throw in some normal functionality for good measure.

TRICKS:
- keep in mind that the dojo is a multi-docker infra running inside the {DOJO_CONTAINER} docker-in-docker container.
- feel free to "cheat": you can `docker exec {DOJO_CONTAINER} docker exec $WHATEVER` directly into containers to look around
- `docker exec -i {DOJO_CONTAINER} dojo enter -s $USER <<< "cat /flag"` is especially useful for getting flags without having to solve the actual tricky challenges, to test that part of the dojo's functionality. You will almost certainly have to do this to solve challenges to test functionality!
- this environment is disposable for your use; don't worry about breaking things

IMPORTANT: 
- Focus ONLY on actual broken functionality, not design preferences
- Actually use the dojo, don't just navigate around.
- It is a known issue that sensai does not work in CI environments. Please ignore it.

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
    print(f"::error::GPT exploration failed with return code {result.returncode}")
    if result.stderr:
        print("::group::Error output")
        print(result.stderr)
        print("::endgroup::")
    raise RuntimeError(f"GPT exploration failed: {result.stderr}")

exploration_result = result.stdout
print("::group::Full GPT Output")
print(exploration_result)
print("::endgroup::")
    
try:
    exploration_result = exploration_result.split("] codex\n")[-1].strip()
    json_start = exploration_result.find('{')
    json_end = exploration_result.rfind('}') + 1
    if json_start >= 0 and json_end > json_start:
        json_str = exploration_result[json_start:json_end]
        report = json.loads(json_str)
    else:
        report = json.loads(exploration_result.strip())
    
    print("\n::group::Exploration Report")
    print(f"Result: {'PASS ✅' if report['pass'] else 'FAIL ❌'}")
    print(f"Pages explored: {len(report.get('pages_explored', []))}")
    for page in report.get('pages_explored', []):
        print(f"  - {page}")
    print("::endgroup::")
    
    if report.get('issues_found'):
        print(f"::group::Issues Found ({len(report['issues_found'])} total)")
        
        for issue in report['issues_found']:
            severity = issue.get('severity', 'unknown')
            severity_icon = {'critical': '🔴', 'major': '🟠', 'minor': '🟡'}.get(severity.lower(), '⚪')
            
            if severity.lower() == 'critical':
                print(f"::error title=Critical Issue::{issue['issue']} (at {issue['page']})")
            elif severity.lower() == 'major':
                print(f"::warning title=Major Issue::{issue['issue']} (at {issue['page']})")
            
            print(f"  {severity_icon} [{severity.upper()}] {issue['page']}")
            print(f"    {issue['issue']}")
        
        print("::endgroup::")
    else:
        print("::notice::No issues found! ✅")
    
    print("::group::Summary")
    print(f"\nSummary: {report.get('summary', 'No summary provided')}")
    print("::endgroup::")
    
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
    
except json.JSONDecodeError as e:
    print(f"::warning::Could not parse GPT's JSON response: {e}")
    sys.exit(1)
