#!/usr/bin/env python3
"""
Example: Simple API Client

This demonstrates a skill that makes authenticated API requests.
It works identically with or without the sandbox — the only difference
is that with the sandbox, credentials are dummy values that get replaced
by the proxy.

Usage:
    # Without sandbox (direct access):
    SANDBOX_ENABLED=0 python examples/simple_client.py

    # With sandbox:
    docker compose up -d
    ./sandbox-run.sh python examples/simple_client.py

Try modifying the API calls — the sandbox will block requests to
non-whitelisted domains.
"""

import os
import sys
import json

# Import requests (available in sandbox image)
import requests


def check_env():
    """Show what credentials the process sees."""
    print("\n" + "=" * 60)
    print("Environment Variables Seen by This Process:")
    print("=" * 60)
    
    cred_keys = [
        "JIRA_TOKEN", "JIRA_URL",
        "API_KEY", "API_URL", 
        "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_URL",
        "MICROSOFT_TOKEN", "GRAPH_URL",
    ]
    
    for key in cred_keys:
        val = os.environ.get(key, "(not set)")
        # Show truncated value for secrets
        if "KEY" in key or "TOKEN" in key or "SECRET" in key:
            if len(val) > 10:
                val = val[:4] + "..." + val[-4:]
        print(f"  {key}: {val}")
    
    print()


def call_jira():
    """Call Jira API through the proxy."""
    url = os.environ.get("JIRA_URL", "")
    token = os.environ.get("JIRA_TOKEN", "")
    
    if not url or not token:
        print("[Jira] Skipped: JIRA_URL or JIRA_TOKEN not set")
        return
    
    # If sandbox is active, URL points to proxy
    if "/jira" in url:
        api_url = f"{url}/rest/api/2/myself"
    else:
        api_url = f"{url}/rest/api/2/myself"
    
    print(f"[Jira] Calling: {api_url}")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        print(f"[Jira] Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"[Jira] Logged in as: {data.get('displayName', 'unknown')}")
        else:
            print(f"[Jira] Response: {resp.text[:200]}")
    except Exception as e:
        print(f"[Jira] Error: {e}")


def call_api():
    """Call generic API through the proxy."""
    url = os.environ.get("API_URL", "")
    key = os.environ.get("API_KEY", "")
    
    if not url or not key:
        print("[API] Skipped: API_URL or API_KEY not set")
        return
    
    # If sandbox is active, URL points to proxy
    if "/api" in url:
        api_url = f"{url}/v1/status"
    else:
        api_url = f"{url}/v1/status"
    
    print(f"[API] Calling: {api_url}")
    
    headers = {"X-API-Key": key}
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        print(f"[API] Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"[API] Response: {resp.json()}")
    except Exception as e:
        print(f"[API] Error: {e}")


def call_graph():
    """Call Microsoft Graph API through the proxy."""
    url = os.environ.get("GRAPH_URL", "")
    token = os.environ.get("MICROSOFT_TOKEN", "")
    
    if not url or not token:
        print("[Graph] Skipped: GRAPH_URL or MICROSOFT_TOKEN not set")
        return
    
    # If sandbox is active, URL points to proxy
    if "/graph" in url:
        api_url = f"{url}/v1.0/me"
    else:
        api_url = f"{url}/v1.0/me"
    
    print(f"[Graph] Calling: {api_url}")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        print(f"[Graph] Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"[Graph] User: {data.get('displayName', 'unknown')}")
    except Exception as e:
        print(f"[Graph] Error: {e}")


def test_blocked():
    """Try to access a blocked domain (should be blocked by proxy)."""
    print("\n[Security Test] Attempting blocked request...")
    
    # This should be blocked by the proxy whitelist
    try:
        resp = requests.get(
            "http://credential-proxy:9199/evil/exfil",
            timeout=5
        )
        print(f"[Security] Got response: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[Security] Request blocked/error: {e}")


def main():
    print("Agent Credential Sandbox - Example Client")
    print("=" * 60)
    
    # Show environment
    check_env()
    
    # Make API calls
    call_jira()
    call_api()
    call_graph()
    
    # Test security
    test_blocked()
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()