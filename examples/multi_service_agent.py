#!/usr/bin/env python3
"""
Example: Multi-Service Agent

This demonstrates an agent that accesses multiple services:
- Jira for issue tracking
- S3-compatible storage for file operations
- A generic API for external data

The sandbox enforces per-skill permissions — this skill can only
access the routes it needs.

Usage:
    docker compose up -d
    ./sandbox-run.sh python examples/multi_service_agent.py
"""

import os
import sys
import json
import requests


def log_service(name, message):
    print(f"[{name}] {message}")


class JiraClient:
    """Simple Jira API client."""
    
    def __init__(self):
        self.url = os.environ.get("JIRA_URL", "")
        self.token = os.environ.get("JIRA_TOKEN", "")
    
    def get_issues(self, jql="assignee=currentUser"):
        if not self.url or not self.token:
            log_service("Jira", "Skipped: not configured")
            return []
        
        # Proxy handles URL translation
        api_url = f"{self.url}/rest/api/2/search?jql={jql}&maxResults=5"
        
        log_service("Jira", f"Fetching issues...")
        try:
            resp = requests.get(
                api_url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                issues = data.get("issues", [])
                log_service("Jira", f"Found {len(issues)} issues")
                return issues
            else:
                log_service("Jira", f"Error: {resp.status_code}")
        except Exception as e:
            log_service("Jira", f"Error: {e}")
        return []


class S3Client:
    """S3-compatible storage client."""
    
    def __init__(self):
        self.url = os.environ.get("S3_URL", "")
        self.access_key = os.environ.get("S3_ACCESS_KEY", "")
        self.secret_key = os.environ.get("S3_SECRET_KEY", "")
    
    def list_buckets(self):
        if not self.url or not self.access_key:
            log_service("S3", "Skipped: not configured")
            return []
        
        # S3 requires SigV4 signing — handled by the proxy
        # The client uses dummy credentials; proxy re-signs with real ones
        import boto3
        from botocore.config import Config
        
        # Parse URL to get host
        host = self.url.replace("http://", "").replace("https://", "").rstrip("/")
        
        log_service("S3", f"Listing buckets at {host}...")
        try:
            client = boto3.client(
                's3',
                endpoint_url=self.url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name='us-east-1',
                config=Config(signature_version='s3v4')
            )
            resp = client.list_buckets()
            buckets = [b["Name"] for b in resp.get("Buckets", [])]
            log_service("S3", f"Found {len(buckets)} buckets: {buckets}")
            return buckets
        except Exception as e:
            log_service("S3", f"Error: {e}")
        return []


class APIClient:
    """Generic REST API client."""
    
    def __init__(self):
        self.url = os.environ.get("API_URL", "")
        self.key = os.environ.get("API_KEY", "")
    
    def get_status(self):
        if not self.url or not self.key:
            log_service("API", "Skipped: not configured")
            return {}
        
        api_url = f"{self.url}/v1/status"
        
        log_service("API", f"Fetching status...")
        try:
            resp = requests.get(
                api_url,
                headers={"X-API-Key": self.key},
                timeout=10
            )
            if resp.status_code == 200:
                log_service("API", f"Status: {resp.json()}")
                return resp.json()
            else:
                log_service("API", f"Error: {resp.status_code}")
        except Exception as e:
            log_service("API", f"Error: {e}")
        return {}


def show_environment():
    """Display credential environment."""
    print("\n" + "=" * 60)
    print("Credential Environment")
    print("=" * 60)
    
    # Redact secrets for display
    def redact(val):
        if not val:
            return "(not set)"
        if len(val) > 8:
            return val[:4] + "..." + val[-4:]
        return val
    
    print(f"  JIRA_URL:     {os.environ.get('JIRA_URL', '(not set)')}")
    print(f"  JIRA_TOKEN:   {redact(os.environ.get('JIRA_TOKEN', ''))}")
    print(f"  S3_URL:       {os.environ.get('S3_URL', '(not set)')}")
    print(f"  S3_ACCESS_KEY: {redact(os.environ.get('S3_ACCESS_KEY', ''))}")
    print(f"  API_URL:      {os.environ.get('API_URL', '(not set)')}")
    print(f"  API_KEY:      {redact(os.environ.get('API_KEY', ''))}")
    print()


def main():
    print("=" * 60)
    print("Multi-Service Agent Example")
    print("=" * 60)
    
    show_environment()
    
    # Initialize clients
    jira = JiraClient()
    s3 = S3Client()
    api = APIClient()
    
    # Execute workflows
    print("\n--- Running Agent Workflows ---\n")
    
    issues = jira.get_issues()
    buckets = s3.list_buckets()
    status = api.get_status()
    
    print("\n--- Summary ---")
    print(f"Issues: {len(issues)}")
    print(f"Buckets: {len(buckets)}")
    print(f"API Status: {'OK' if status else 'N/A'}")
    print("\nDone!")


if __name__ == "__main__":
    main()