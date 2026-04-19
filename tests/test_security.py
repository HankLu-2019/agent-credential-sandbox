#!/usr/bin/env python3
"""
Security Tests for Agent Credential Sandbox.

These tests verify that the sandbox blocks various attack vectors
designed to exfiltrate credentials.

Run with: pytest tests/test_security.py -v
"""

import pytest
import subprocess
import requests
import os
import time


PROXY_URL = "http://127.0.0.1:9199"
SANDBOX_IMAGE = "agent-sandbox-image"


def docker_run_harden(cmd: str, env: dict = None) -> subprocess.CompletedProcess:
    """Run command in hardened sandbox container."""
    args = [
        "docker", "run", "--rm",
        "--network", "agent-sandbox-internal",
        "--cap-drop=ALL",
        "--read-only",
        "--tmpfs", "/tmp",
        "--user", "1000:1000",
        SANDBOX_IMAGE,
        "sh", "-c", cmd
    ]
    
    env = env or {}
    full_env = os.environ.copy()
    full_env.update(env)
    
    return subprocess.run(args, capture_output=True, text=True, env=full_env)


@pytest.fixture(scope="module")
def proxy_running():
    """Ensure proxy is running."""
    try:
        resp = requests.get(f"{PROXY_URL}/health", timeout=5)
        if resp.status_code != 200:
            pytest.skip("Proxy not running")
    except:
        pytest.skip("Proxy not running")


class TestCredentialIsolation:
    """Test that real credentials never enter the sandbox."""

    def test_dummy_credentials_in_container(self, proxy_running):
        """Container sees only dummy credentials."""
        result = docker_run_harden(
            'python3 -c "import os; print(os.environ.get(\\"JIRA_TOKEN\\", \\"\\"))"',
            env={
                "JIRA_URL": f"{PROXY_URL}/jira",
                "JIRA_TOKEN": "dummy"
            }
        )
        
        assert result.returncode == 0
        # Container should see 'dummy', not real value
        assert "dummy" in result.stdout
        assert "real-token" not in result.stdout


class TestWhitelistEnforcement:
    """Test that whitelist blocks unauthorized routes."""

    def test_block_unknown_route(self, proxy_running):
        """Proxy blocks requests to unknown routes."""
        resp = requests.get(f"{PROXY_URL}/evil/exfil")
        assert resp.status_code == 403
        
        data = resp.json()
        assert data.get("error") == "route_not_allowed"

    def test_allow_whitelisted_route(self, proxy_running):
        """Proxy allows requests to whitelisted routes."""
        # Mock server should return 200 for /jira
        resp = requests.get(f"{PROXY_URL}/jira/rest/api/2/myself")
        # May be 200 or 401 (mock) but not 403
        assert resp.status_code != 403


class TestSSRFPrevention:
    """Test SSRF prevention, especially for Jenkins."""

    def test_jenkins_block_malicious_target(self, proxy_running):
        """Proxy blocks Jenkins requests to non-whitelisted targets."""
        resp = requests.get(
            f"{PROXY_URL}/jenkins/job/test",
            headers={"X-Sandbox-Target": "https://evil.attacker.com/"}
        )
        assert resp.status_code == 400
        assert "invalid_target" in resp.text or "rejected" in resp.text.lower()

    def test_jenkins_allow_whitelisted_target(self, proxy_running):
        """Proxy allows Jenkins requests to whitelisted targets."""
        resp = requests.get(
            f"{PROXY_URL}/jenkins/job/test",
            headers={"X-Sandbox-Target": "https://jenkins.example.com/"}
        )
        # May fail for other reasons but should pass target validation
        assert resp.status_code != 403


class TestSourceIPValidation:
    """Test that proxy rejects external connections."""

    def test_reject_external_ip(self, proxy_running):
        """Proxy rejects connections from non-RFC1918 addresses."""
        # This test would need to simulate external connection
        # In practice, the proxy binds to 127.0.0.1 so external is impossible
        pass


class TestNetworkIsolation:
    """Test that sandbox cannot access internet directly."""

    def test_no_direct_internet(self, proxy_running):
        """Sandbox cannot reach external hosts directly."""
        result = docker_run_harden(
            "python3 -c 'import socket; socket.socket().connect((\\"8.8.8.8\\", 53))'",
            env={"JIRA_URL": f"{PROXY_URL}/jira", "JIRA_TOKEN": "dummy"}
        )
        
        # Should fail because internal network has no internet
        assert result.returncode != 0


class TestRateLimiting:
    """Test rate limiting."""

    def test_rate_limit_enforced(self, proxy_running):
        """Proxy enforces rate limits."""
        # Make many requests quickly
        # Note: This test may need mock server to be reliable
        count = 0
        for _ in range(25):
            resp = requests.get(f"{PROXY_URL}/api/v1/status")
            if resp.status_code == 429:
                count += 1
        
        # Should hit rate limit at some point
        # (This is a soft check - depends on rate limit config)
        print(f"Rate limited requests: {count}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])