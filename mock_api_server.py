#!/usr/bin/env python3
"""
Mock API Server for local testing.

Simulates Jira, generic API, and Microsoft Graph endpoints.
Allows testing the sandbox without real external services.
"""

import json
import http.server
import socketserver
import random
import sys


PORT = 8080


class MockAPIHandler(http.server.BaseHTTPRequestHandler):
    """Mock API endpoints for testing."""

    def log_message(self, fmt, *args):
        print(f"[MockAPI] {fmt % args}")

    def send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path

        # Health check
        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        # Mock Jira
        if path.startswith("/jira/"):
            if "myself" in path:
                self.send_json(200, {
                    "displayName": "Test User",
                    "emailAddress": "test@example.com",
                    "accountId": "12345678"
                })
            elif "search" in path:
                self.send_json(200, {
                    "issues": [
                        {"key": "TEST-1", "fields": {"summary": "Test issue 1"}},
                        {"key": "TEST-2", "fields": {"summary": "Test issue 2"}},
                    ],
                    "total": 2
                })
            else:
                self.send_json(200, {"result": "jira-ok"})
            return

        # Mock API
        if path.startswith("/api/"):
            if "status" in path:
                self.send_json(200, {
                    "status": "operational",
                    "version": "1.0.0",
                    "timestamp": "2024-01-01T00:00:00Z"
                })
            else:
                self.send_json(200, {"result": "api-ok"})
            return

        # Mock Graph
        if path.startswith("/graph/"):
            if "me" in path:
                self.send_json(200, {
                    "displayName": "Test User",
                    "userPrincipalName": "test@example.com",
                    "id": "abcdef123456"
                })
            else:
                self.send_json(200, {"result": "graph-ok"})
            return

        # 404 for unknown paths
        self.send_json(404, {"error": "not found"})


class ReuseAddrTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    print(f"Starting Mock API Server on port {PORT}")
    print("Endpoints:")
    print("  GET /health           - Health check")
    print("  GET /jira/...         - Mock Jira API")
    print("  GET /api/...          - Mock generic API")
    print("  GET /graph/...        - Mock Microsoft Graph")
    print()

    with ReuseAddrTCPServer(("", PORT), MockAPIHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            sys.exit(0)


if __name__ == "__main__":
    main()