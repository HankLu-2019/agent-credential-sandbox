# Contributing to Agent Credential Sandbox

Thank you for your interest in contributing!

## Getting Started

### Prerequisites

- Python 3.12+
- Docker
- Git

### Development Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/agent-credential-sandbox.git
cd agent-credential-sandbox

# Create a virtual environment (for local testing)
python3 -m venv venv
source venv/bin/activate

# Install test dependencies
pip install pytest requests

# Copy environment template
cp .env.example .env
```

### Running Locally

```bash
# Start the full stack
docker compose up -d

# Run the sandbox runner
./sandbox-run.sh python examples/simple_client.py

# Run tests
pytest tests/ -v
```

## Making Changes

1. **Fork** the repository on GitHub
2. **Create** a feature branch: `git checkout -b feature/my-feature`
3. **Make** your changes
4. **Test** locally with `docker compose up -d`
5. **Commit** with clear commit messages
6. **Push** to your fork
7. **Open** a Pull Request

## Code Style

- Python: Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Bash: Use shellcheck for linting
- JSON: Valid JSON for all config files

## Project Structure

```
agent-credential-sandbox/
├── proxy/
│   ├── credential_proxy.py   # Main proxy (stdlib only!)
│   └── whitelist.json        # Route configuration
├── examples/                  # Example skills
├── tests/                     # Test suite
├── sandbox-run.sh            # Sandbox orchestrator
├── docker-compose.yml        # Local dev stack
└── Dockerfile.*              # Container images
```

## Submitting Changes

### Before You Submit

- [ ] Tests pass: `pytest tests/ -v`
- [ ] Docker Compose starts: `docker compose up -d`
- [ ] Examples run: `./sandbox-run.sh python examples/simple_client.py`
- [ ] No hardcoded secrets or credentials

### Pull Request Process

1. Update documentation if needed
2. Add tests for new features
3. Update the CHANGELOG if applicable
4. Request review from maintainers

## Publishing to GitHub

### Initial Push (if starting fresh)

```bash
# Navigate to project directory
cd agent-credential-sandbox

# Initialize git (if not done)
git init
git add .
git commit -m "Initial: Agent Credential Sandbox"

# Create repository on GitHub, then add remote:
git remote add origin https://github.com/YOUR_USERNAME/agent-credential-sandbox.git

# Push to GitHub
git push -u origin master
```

### Subsequent Changes

```bash
# Make changes, then
git add .
git commit -m "Description of changes"
git push origin master
```

### Using a Feature Branch

```bash
git checkout -b feature/my-new-feature
# make changes
git add .
git commit -m "Add new feature"
git push -u origin feature/my-new-feature
# Then open PR from GitHub UI
```

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Getting Help

- Open an [issue](https://github.com/yourusername/agent-credential-sandbox/issues)
- Check existing [discussions](https://github.com/yourusername/agent-credential-sandbox/discussions)