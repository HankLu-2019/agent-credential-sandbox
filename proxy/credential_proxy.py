#!/usr/bin/env python3
"""
Credential Isolation Proxy — Core component of Agent Credential Sandbox.

Intercepts HTTP requests from sandboxed containers, validates them against
a domain whitelist, injects real credentials, and forwards to the real API.

SECURITY: Uses only Python stdlib — zero third-party dependencies.
"""

import argparse
import base64
import hashlib
import hmac
import http.client
import http.server
import ipaddress
import json
import logging
import os
import pathlib
import re
import ssl
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("credential_proxy")

CHUNK_SIZE = 65536  # 64 KB

# ---------------------------------------------------------------------------
# Credential Store
# ---------------------------------------------------------------------------
def load_credential_store(path: str) -> dict:
    """Load KEY=VALUE pairs from the credential store file."""
    creds = {}
    p = pathlib.Path(path)
    if not p.exists():
        logger.warning("Credential store not found: %s", path)
        return creds
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip()
    return creds

# ---------------------------------------------------------------------------
# Token Bucket Rate Limiter
# ---------------------------------------------------------------------------
class TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate: float, burst: int):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Consume tokens. Returns True if allowed, False if rate-limited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

# ---------------------------------------------------------------------------
# SigV4 Re-signing (for S3-compatible APIs)
# ---------------------------------------------------------------------------
def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def _derive_signing_key(secret: str, date_str: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret).encode("utf-8"), date_str)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")

def resign_sigv4(
    method: str,
    path: str,
    query: str,
    headers: dict,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    target_host: str,
) -> dict:
    """Re-sign request with real S3 credentials."""
    # Get timestamp from incoming request
    amz_date = headers.get("x-amz-date", "")
    if not amz_date:
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers["x-amz-date"] = amz_date
    date_str = amz_date[:8]

    # Extract signed headers
    auth_hdr = headers.get("authorization", "")
    signed_headers_str = "host;x-amz-content-sha256;x-amz-date"
    m = re.search(r"SignedHeaders=([^,\s]+)", auth_hdr)
    if m:
        signed_headers_str = m.group(1)
    signed_headers_list = signed_headers_str.split(";")

    # Rewrite host
    headers["host"] = target_host

    # Strip old auth
    headers.pop("authorization", None)
    headers.pop("x-amz-security-token", None)

    # Content SHA256
    streaming = headers.get("x-amz-content-sha256", "").upper() == "STREAMING-AWS4-HMAC-SHA256-PAYLOAD"
    content_sha256 = "UNSIGNED-PAYLOAD" if streaming else hashlib.sha256(body).hexdigest()
    headers["x-amz-content-sha256"] = content_sha256

    # Canonical headers
    canonical_header_lines = []
    for hdr_name in sorted(signed_headers_list):
        hdr_val = re.sub(r"\s+", " ", headers.get(hdr_name, "").strip())
        canonical_header_lines.append(f"{hdr_name}:{hdr_val}")
    canonical_headers = "\n".join(canonical_header_lines) + "\n"

    # Canonical URI
    safe_path = urllib.parse.quote(urllib.parse.unquote(path), safe="/")
    if not safe_path.startswith("/"):
        safe_path = "/" + safe_path

    # Canonical query string
    canonical_qs = ""
    if query:
        params = []
        for part in query.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
            else:
                k, v = part, ""
            params.append((
                urllib.parse.quote(urllib.parse.unquote(k)),
                urllib.parse.quote(urllib.parse.unquote(v))
            ))
        params.sort()
        canonical_qs = "&".join(f"{k}={v}" for k, v in params)

    # Build canonical request
    canonical_request = "\n".join([
        method.upper(),
        safe_path,
        canonical_qs,
        canonical_headers,
        signed_headers_str,
        content_sha256,
    ])

    # String to sign
    credential_scope = f"{date_str}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    # Sign
    signing_key = _derive_signing_key(secret_key, date_str, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    # New Authorization header
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, "
        f"Signature={signature}"
    )
    return headers

# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------
class CredentialProxyHandler(http.server.BaseHTTPRequestHandler):
    """Handles and proxies HTTP requests with credential injection."""

    def log_message(self, fmt, *args):
        pass  # We do our own logging

    def _client_ip(self) -> str:
        return self.client_address[0]

    def _validate_source_ip(self) -> bool:
        """Accept only RFC1918 + loopback addresses."""
        try:
            addr = ipaddress.ip_address(self._client_ip())
        except ValueError:
            return False
        allowed = [
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("127.0.0.0/8"),
        ]
        return any(addr in net for net in allowed)

    def _match_route(self, path: str):
        """Find first matching route config."""
        for route in self.server.whitelist.get("routes", []):
            if path.startswith(route["prefix"]):
                return route
        return None

    def _check_skill_permission(self, route: dict, skill_id: Optional[str]) -> bool:
        """Enforce per-skill route permissions."""
        if not skill_id:
            return True
        perms = self.server.whitelist.get("skill_permissions", {})
        allowed = perms.get(skill_id, [])
        if allowed is None:  # unknown skill
            return True
        return route["prefix"] in allowed

    def _cred(self, key: str) -> str:
        return self.server.credentials.get(key, "")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("content-length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _inject_auth(self, route: dict, headers: dict):
        """Inject authentication based on route config."""
        auth_type = route.get("auth_type", "")

        if auth_type == "bearer":
            token = self._cred(route["cred_env"])
            headers["authorization"] = f"Bearer {token}"

        elif auth_type == "basic":
            user = self._cred(route["cred_env_user"])
            passwd = self._cred(route["cred_env_pass"])
            encoded = base64.b64encode(f"{user}:{passwd}".encode()).decode()
            headers["authorization"] = f"Basic {encoded}"

        elif auth_type == "apikey":
            key = self._cred(route["cred_env"])
            header = route.get("apikey_header", "X-API-Key")
            headers[header.lower()] = key

        return headers

    def _resolve_target(self, route: dict, path: str, query: str) -> Optional[str]:
        """Resolve target URL for this route."""
        # Jenkins: use X-Sandbox-Target header with validation
        if route.get("use_x_sandbox_target"):
            target = self.headers.get("x-sandbox-target", "").strip()
            if not target:
                logger.warning("Missing X-Sandbox-Target header")
                return None
            patterns = route.get("target_patterns", [])
            if not any(re.match(p, target) for p in patterns):
                logger.warning("X-Sandbox-Target '%s' rejected", target)
                return None
            stripped = path[len(route["prefix"]):]
            if not stripped.startswith("/"):
                stripped = "/" + stripped
            url = target.rstrip("/") + stripped
            return url + (f"?{query}" if query else "")

        # Standard: resolve from environment/credentials
        target_env = route.get("target_env", "")
        target = (
            os.environ.get(target_env)
            or self.server.credentials.get(target_env)
            or route.get("target_default", "")
        )
        if not target:
            logger.error("No target for route %s", route["prefix"])
            return None

        stripped = path[len(route["prefix"]):]
        if not stripped.startswith("/"):
            stripped = "/" + stripped
        url = target.rstrip("/") + stripped
        return url + (f"?{query}" if query else "")

    def _forward(self, target_url: str, method: str, headers: dict, body: bytes):
        """Forward request to target, return (status, headers, body)."""
        parsed = urllib.parse.urlparse(target_url)
        use_tls = parsed.scheme == "https"
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # Create connection
        if use_tls:
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(host, context=ctx, timeout=30)
        else:
            conn = http.client.HTTPConnection(host, timeout=30)

        # Strip hop-by-hop headers
        hop_by_hop = {"connection", "keep-alive", "proxy-authenticate",
                      "proxy-authorization", "te", "trailers",
                      "transfer-encoding", "upgrade"}
        send_headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}
        send_headers["connection"] = "close"

        conn.request(method, path, body=body or None, headers=send_headers)
        resp = conn.getresponse()
        resp_body = resp.read()
        resp_headers = dict(resp.getheaders())
        conn.close()
        return resp.status, resp_headers, resp_body

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle()
    def do_POST(self):
        self._handle()
    def do_PUT(self):
        self._handle()
    def do_PATCH(self):
        self._handle()
    def do_DELETE(self):
        self._handle()

    def _handle(self):
        """Main request handler."""
        t_start = time.perf_counter()

        # 1. Source IP validation
        if not self._validate_source_ip():
            self.send_response(403)
            self.end_headers()
            return

        # 2. Parse path
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = parsed.query

        # 3. Health check
        if path == "/health":
            self._send_json(200, {
                "status": "ok",
                "uptime": int(time.monotonic() - self.server.start_time),
                "routes": len(self.server.whitelist.get("routes", [])),
            })
            return

        # 4. Route matching
        route = self._match_route(path)
        if route is None:
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.info("%s %s → [NO ROUTE] 403 (%.1fms)", self.command, path, elapsed)
            self._send_json(403, {"error": "route_not_allowed"})
            return

        # 5. Per-skill permission
        skill_id = self.headers.get("x-skill-id", "").strip() or None
        if not self._check_skill_permission(route, skill_id):
            self._send_json(403, {"error": "skill_not_permitted"})
            return

        # 6. Rate limiting
        limiter = self.server.rate_limiters.get(route["prefix"])
        if limiter and not limiter.consume():
            self._send_json(429, {"error": "rate_limit_exceeded"})
            return

        # 7. Read body
        body = self._read_body()

        # 8. Build forwarded headers
        fwd_headers = {k.lower(): v for k, v in self.headers.items()}
        fwd_headers = {k: v for k, v in fwd_headers.items()
                       if not k.startswith("x-sandbox-") and k != "x-skill-id"}

        # 9. Resolve target URL
        target_url = self._resolve_target(route, path, query)
        if target_url is None:
            self._send_json(400, {"error": "invalid_target"})
            return

        # 10. Inject auth
        fwd_headers = self._inject_auth(route, fwd_headers)

        # 11. SigV4 re-signing for S3
        if route.get("auth_type") == "sigv4":
            parsed_target = urllib.parse.urlparse(target_url)
            access_key = self._cred(route["cred_env_key"])
            secret_key = self._cred(route["cred_env_secret"])
            fwd_headers = resign_sigv4(
                self.command, parsed_target.path, parsed_target.query,
                fwd_headers, body, access_key, secret_key,
                route.get("sigv4_region", "us-east-1"),
                route.get("sigv4_service", "s3"),
                parsed_target.netloc,
            )

        # 12. Forward request
        try:
            status, resp_headers, resp_body = self._forward(
                target_url, self.command, fwd_headers, body
            )
        except Exception as e:
            logger.error("Proxy error: %s", e)
            self._send_json(502, {"error": "upstream_error", "detail": str(e)})
            return

        # 13. Send response
        elapsed = (time.perf_counter() - t_start) * 1000
        logger.info("%s %s → %s [%d] %.1fms",
                    self.command, path, route["prefix"], status, elapsed)

        self.send_response(status)
        for k, v in resp_headers.items():
            if k.lower() not in hop_by_hop:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

hop_by_hop = {"connection", "keep-alive", "proxy-authenticate",
              "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade"}

# ---------------------------------------------------------------------------
# Proxy Server
# ---------------------------------------------------------------------------
class CredentialProxyServer(http.server.ThreadingHTTPServer):
    """HTTP server with credential injection and whitelist enforcement."""

    def __init__(self, host: str, port: int, whitelist_path: str, creds_path: str):
        super().__init__((host, port), CredentialProxyHandler)
        self.start_time = time.monotonic()

        # Load whitelist
        with open(whitelist_path) as f:
            self.whitelist = json.load(f)

        # Load credentials
        self.credentials = load_credential_store(creds_path)
        logger.info("Loaded %d credentials from %s", len(self.credentials), creds_path)

        # Build rate limiters
        self.rate_limiters = {}
        for route in self.whitelist.get("routes", []):
            rl = route.get("rate_limit")
            if rl:
                rate = float(rl.get("rate", 10))
                burst = int(rl.get("burst", 20))
                self.rate_limiters[route["prefix"]] = TokenBucket(rate, burst)

        logger.info("Proxy configured with %d routes", len(self.whitelist.get("routes", [])))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Credential Isolation Proxy")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=9199, help="Port")
    parser.add_argument("--whitelist", required=True, help="Path to whitelist.json")
    parser.add_argument("--kiroenv", required=True, help="Path to credential store")
    args = parser.parse_args()

    server = CredentialProxyServer(args.host, args.port, args.whitelist, args.kiroenv)
    logger.info("Starting proxy on %s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()