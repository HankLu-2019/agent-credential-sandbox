# Agent Credential Sandbox - Setup Guide

This guide walks you through setting up the credential sandbox for your AI agents.

## Prerequisites

- Docker installed and running
- Python 3.12+ (for local testing)
- `docker-compose` or `docker compose`

## Step 1: Clone and Setup

```bash
# Clone the repository (replace with your fork)
git clone https://github.com/yourusername/agent-credential-sandbox.git
cd agent-credential-sandbox
```

## Step 2: Configure Credentials

```bash
# Copy the example env file
cp .env.example .env

# Edit with your real credentials
nano .env
```

Your `.env` should look like:
```bash
# Jira
JIRA_TOKEN=your-jira-personal-access-token
JIRA_URL=https://your-company.atlassian.net

# S3-compatible storage
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_URL=https://s3.your-company.com

# Generic API
API_KEY=your-api-key
API_URL=https://api.your-company.com
```

## Step 3: Configure Routes

Edit `proxy/whitelist.json` to define which APIs your agents can access:

```json
{
  "routes": [
    {
      "prefix": "/jira",
      "target_env": "JIRA_URL",
      "auth_type": "bearer",
      "cred_env": "JIRA_TOKEN"
    }
  ]
}
```

### Route Configuration Options

| Field | Description |
|-------|-------------|
| `prefix` | URL path prefix (e.g., `/jira`) |
| `target_env` | Environment variable for target URL |
| `auth_type` | `bearer`, `basic`, `apikey`, or `sigv4` |
| `cred_env` | Credential environment variable |
| `rate_limit` | Optional rate limiting (requests/sec) |

## Step 4: Start the Proxy

```bash
# Start just the proxy (for production use)
docker compose up -d proxy

# Or start full stack (proxy + mock services for testing)
docker compose up -d
```

Verify the proxy is running:
```bash
curl http://127.0.0.1:9199/health
```

## Step 5: Run Your Agent

### Option A: Using the sandbox runner

```bash
# Run your agent in the sandbox
./sandbox-run.sh python my_agent.py

# Or run without sandbox (for debugging)
./sandbox-run.sh --direct python my_agent.py
```

### Option B: Manual Docker run

```bash
docker run --rm \
  --network agent-sandbox-internal \
  --cap-drop=ALL \
  --read-only \
  --tmpfs /tmp \
  --user 1000:1000 \
  -e JIRA_URL=http://credential-proxy:9199/jira \
  -e JIRA_TOKEN=dummy \
  agent-sandbox-image \
  python my_agent.py
```

## Testing

Start mock services for local testing:
```bash
docker compose up -d mock-api minio
```

Run example:
```bash
./sandbox-run.sh python examples/simple_client.py
```

Run security tests:
```bash
pip install pytest requests
pytest tests/test_security.py -v
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ Host Machine                                                     │
│                                                                  │
│  .env (real credentials) ─────────────────────────────────┐     │
│                                                          │     │
│  ┌───────────────────────────────────────────────────────▼────┐ │
│  │ Credential Proxy (Python stdlib, ~350 lines)             │ │
│  │ - Validates routes against whitelist                     │ │
│  │ - Injects real credentials                               │ │
│  │ - Enforces rate limits                                   │ │
│  └───────────────────────┬────────────────────────────────────┘ │
│                          │                                       │
│  ┌───────────────────────▼────────────────────────────────────┐ │
│  │ Internal Network (--internal, no internet)                │ │
│  │                                                               │ │
│  │   ┌────────────────┐    ┌────────────────┐                  │ │
│  │   │ Sandbox        │    │ Mock Services  │                  │ │
│  │   │ Container      │───►│ (for testing)  │                  │ │
│  │   │ (dummy creds)  │    └────────────────┘                  │ │
│  │   └────────────────┘                                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                          │                                       │
│                   (HTTPS + real creds)                           │
│                          │                                       │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ External APIs (Jira, Jenkins, S3, etc.)                     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Proxy won't start
```bash
# Check logs
docker logs credential-proxy

# Check port availability
lsof -i :9199
```

### Connection refused
```bash
# Verify network exists
docker network ls | grep agent-sandbox

# Re-create network
docker network create --driver bridge --internal agent-sandbox-internal
```

### "Dummy" credentials in logs
This is correct! The sandbox should see dummy credentials. Real credentials are injected by the proxy.

## Next Steps

- Read the [full paper](./PAPER.md) for academic details
- Check [examples](./examples/) for integration patterns
- Configure per-skill permissions in `whitelist.json`

## Security Notes

1. **Never commit `.env`** — It's already in `.gitignore`
2. **Proxy binds to localhost** — Only local connections accepted
3. **Rate limiting enabled** — Prevents abuse of whitelisted routes
4. **DNS exfiltration** — See documentation for mitigations