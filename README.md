# Agent Credential Sandbox

A credential isolation architecture for AI agents that combines Docker container sandboxing with a credential-injecting reverse proxy.

## The Problem

AI agents need real API credentials (Jira, Jenkins, S3, etc.). But passing credentials directly to agent skills means **any compromised dependency can steal them**.

```
┌──────────────────────────────────────────────────────────────────┐
│  Traditional Setup                                              │
│                                                                  │
│  Skill Code ──► requests library ──► Real Credentials ──► API  │
│       │              │                                         │
│       └──────────────┴──────── Any compromised dependency       │
│                      can steal ALL credentials                  │
└──────────────────────────────────────────────────────────────────┘
```

## The Solution

Skills run in hardened Docker containers with **dummy credentials**. A host-side proxy intercepts all HTTP requests, validates them against a whitelist, injects real credentials, and forwards to the actual APIs.

```
┌──────────────────────────────────────────────────────────────────┐
│  With Agent Credential Sandbox                                  │
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐   │
│  │ Skill Code  │───►│  Sandbox     │───►│ Credential Proxy │   │
│  │ (untrusted) │    │ + dummy creds│    │ + real creds     │   │
│  └─────────────┘    └──────────────┘    └───────────────────┘   │
│                                                │                 │
│                                                ▼                 │
│                                        ┌───────────────────┐     │
│                                        │ Real APIs         │     │
│                                        │ (Jira, Jenkins,   │     │
│                                        │  S3, Teams...)    │     │
│                                        └───────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
```

## Security Properties

| Property | How It's Achieved |
|----------|-------------------|
| **Credential Confidentiality** | Real credentials never enter the sandbox container |
| **API Access Control** | Domain whitelist + Jenkins target validation |
| **Execution Isolation** | `--cap-drop=ALL --read-only --user 1000` |
| **Auditability** | All requests logged with route, target, status |

## Attack Scenarios Blocked

| Attack | Result |
|--------|--------|
| HTTP credential exfiltration | ✅ Blocked by whitelist |
| Environment variable scraping | ✅ Only dummy values in container |
| Direct internet access | ✅ Internal network has no route |
| Supply-chain monkey-patching | ✅ Real credentials injected outside container |
| Filesystem escape | ✅ Read-only FS, non-root user |
| DNS exfiltration | ⚠️ Known limitation (see docs) |

## Quick Start

```bash
# 1. Clone and enter directory
git clone https://github.com/yourusername/agent-credential-sandbox.git
cd agent-credential-sandbox

# 2. Copy and configure credentials
cp .env.example .env
# Edit .env with your real credentials

# 3. Start the proxy
docker compose up -d proxy

# 4. Run your agent in the sandbox
./sandbox-run.sh python my_agent.py
```

## Documentation

- [Paper](./PAPER.md) — Full academic paper describing the architecture
- [Architecture](./docs/architecture.md) — Deep dive into the design
- [API Reference](./docs/api.md) — Whitelist configuration reference
- [Examples](./examples/) — Ready-to-run example skills

## Requirements

- Python 3.12+
- Docker
- No external pip packages (the proxy uses only stdlib!)

## License

MIT