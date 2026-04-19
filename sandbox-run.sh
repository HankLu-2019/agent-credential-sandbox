#!/bin/bash
#
# Sandbox Runner — Execute commands in an isolated sandbox container.
#
# Usage:
#   ./sandbox-run.sh <command> [args...]
#   ./sandbox-run.sh --help
#
# Environment:
#   SANDBOX_ENABLED=0   # Disable sandbox, run directly
#   SANDBOX_PROXY_URL   # Override proxy URL (default: http://kiro-sandbox-proxy:9199)
#

set -e

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROXY_HOST="${SANDBOX_PROXY_HOST:-kiro-sandbox-proxy}"
PROXY_PORT="${SANDBOX_PROXY_PORT:-9199}"
PROXY_URL="http://${PROXY_HOST}:${PROXY_PORT}"
CONTAINER_NAME="agent-sandbox"
IMAGE_NAME="agent-sandbox-image"
PROXY_CONTAINER_NAME="credential-proxy"
INTERNAL_NETWORK="agent-sandbox-internal"
DUMMY_CRED="dummy"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
show_help() {
    cat << EOF
Agent Credential Sandbox Runner

Runs your AI agent skill in an isolated container with dummy credentials.
Real credentials are injected by the proxy at the network boundary.

Usage:
    ./sandbox-run.sh <command> [args...]

Examples:
    ./sandbox-run.sh python my_agent.py --arg1 value1
    ./sandbox-run.sh node agent.js
    ./sandbox-run.sh --direct python my_agent.py  # Skip sandbox

Environment Variables:
    SANDBOX_ENABLED=0      Disable sandbox, run directly
    SANDBOX_PROXY_HOST     Proxy hostname (default: kiro-sandbox-proxy)
    SANDBOX_PROXY_PORT     Proxy port (default: 9199)
    SKILL_ID               Skill identifier for per-skill permissions

Files:
    .env                   Credential store (real credentials)
    proxy/whitelist.json   Route whitelist configuration

EOF
}

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
check_prereqs() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found. Install Docker or set SANDBOX_ENABLED=0"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon not running"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Setup Docker network
# ---------------------------------------------------------------------------
setup_network() {
    if ! docker network inspect ${INTERNAL_NETWORK} &> /dev/null; then
        log_info "Creating internal network: ${INTERNAL_NETWORK}"
        docker network create --driver bridge --internal ${INTERNAL_NETWORK} 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# Build sandbox image
# ---------------------------------------------------------------------------
build_image() {
    if docker image inspect ${IMAGE_NAME} &> /dev/null; then
        log_info "Using cached image: ${IMAGE_NAME}"
        return
    fi

    log_info "Building sandbox image: ${IMAGE_NAME}"

    # Create minimal Dockerfile
    local dockerfile=$(mktemp)
    cat > ${dockerfile} << 'DOCKERFILE'
FROM python:3.12-slim

# Install runtime dependencies
RUN pip install --no-cache-dir requests boto3 && \
    pip cache purge

# Create non-root user
RUN useradd -m -u 1000 sandboxuser

# Switch to non-root
USER sandboxuser
WORKDIR /home/sandboxuser

# Default command
CMD ["python3", "--version"]
DOCKERFILE

    docker build -t ${IMAGE_NAME} -f ${dockerfile} .
    rm -f ${dockerfile}

    log_info "Image built successfully"
}

# ---------------------------------------------------------------------------
# Ensure proxy is running
# ---------------------------------------------------------------------------
ensure_proxy() {
    # Check if proxy is already running
    if docker inspect ${PROXY_CONTAINER_NAME} &> /dev/null; then
        local status=$(docker inspect -f '{{.State.Running}}' ${PROXY_CONTAINER_NAME} 2>/dev/null)
        if [ "$status" = "true" ]; then
            log_info "Proxy already running: ${PROXY_CONTAINER_NAME}"
            # Ensure it's on both networks
            docker network connect ${INTERNAL_NETWORK} ${PROXY_CONTAINER_NAME} 2>/dev/null || true
            return
        fi
    fi

    log_info "Starting credential proxy..."

    # Get the project directory
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local project_dir="$(cd "${script_dir}/.." && pwd)"

    # Build proxy if needed
    if ! docker image inspect agent-proxy-image &> /dev/null; then
        log_info "Building proxy image..."
        local proxy_dockerfile=$(mktemp)
        cat > ${proxy_dockerfile} << 'DOCKERFILE'
FROM python:3.12-slim
COPY proxy/credential_proxy.py /app/proxy.py
COPY proxy/whitelist.json /app/whitelist.json
WORKDIR /app
CMD ["python3", "proxy.py", "--host", "0.0.0.0", "--port", "9199", \
     "--whitelist", "/app/whitelist.json", "--kiroenv", "/creds/.env"]
DOCKERFILE
        docker build -t agent-proxy-image -f ${proxy_dockerfile} ${project_dir}
        rm -f ${proxy_dockerfile}
    fi

    # Start proxy container
    docker run -d \
        --name ${PROXY_CONTAINER_NAME} \
        --network ${INTERNAL_NETWORK} \
        -v "${project_dir}/.env:/creds/.env:ro" \
        -v "${project_dir}/proxy/whitelist.json:/app/whitelist.json:ro" \
        -p "127.0.0.1:9199:9199" \
        agent-proxy-image \
        python3 proxy.py --host 0.0.0.0 --port 9199 \
            --whitelist /app/whitelist.json \
            --kiroenv /creds/.env

    log_info "Proxy started on port 9199"
}

# ---------------------------------------------------------------------------
# Run command in sandbox
# ---------------------------------------------------------------------------
run_sandbox() {
    local cmd="$@"

    # Build environment with dummy credentials pointing to proxy
    local env_args=()
    while IFS='=' read -r key value; do
        if [[ -n "$key" && ! "$key" =~ ^# ]]; then
            # Map real credential keys to proxy URL
            case "$key" in
                JIRA_*|JENKINS_*|KB_*|API_*|MINIO_*|S3_*|TEAMS_*|MICROSOFT_*|GRAPH_*)
                    if [[ "$key" == *_URL ]]; then
                        # Replace URL with proxy prefix
                        local proxy_path=$(echo "$value" | sed 's|https://||' | sed 's|http://||' | cut -d'/' -f1)
                        env_args+=("-e" "${key}=${PROXY_URL}/${key%_URL}")
                    else
                        env_args+=("-e" "${key}=${DUMMY_CRED}")
                    fi
                    ;;
            esac
        fi
    done < .env 2>/dev/null || true

    # Default proxy routes if no .env
    if [ ${#env_args[@]} -eq 0 ]; then
        env_args=(
            -e "JIRA_URL=${PROXY_URL}/jira"
            -e "JIRA_TOKEN=dummy"
            -e "API_URL=${PROXY_URL}/api"
            -e "API_KEY=dummy"
            -e "S3_URL=${PROXY_URL}/s3"
            -e "S3_ACCESS_KEY=dummy"
            -e "S3_SECRET_KEY=dummy"
        )
    fi

    # Add skill ID header if set
    if [ -n "$SKILL_ID" ]; then
        env_args+=("-e" "SKILL_ID=${SKILL_ID}")
    fi

    log_info "Running in sandbox: $cmd"

    docker run --rm \
        --name ${CONTAINER_NAME}-$$ \
        --network ${INTERNAL_NETWORK} \
        --cap-drop=ALL \
        --read-only \
        --tmpfs /tmp \
        --user 1000:1000 \
        --add-host=host.docker.internal:host-gateway \
        ${env_args[@]} \
        ${IMAGE_NAME} \
        sh -c "$cmd"
}

# ---------------------------------------------------------------------------
# Run command directly (no sandbox)
# ---------------------------------------------------------------------------
run_direct() {
    log_warn "Running without sandbox (SANDBOX_ENABLED=0)"
    eval "$@"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    # Handle flags
    case "${1:-}" in
        -h|--help)
            show_help
            exit 0
            ;;
        --direct)
            shift
            run_direct "$@"
            exit $?
            ;;
    esac

    # Skip sandbox if disabled
    if [ "${SANDBOX_ENABLED:-1}" = "0" ]; then
        run_direct "$@"
        exit $?
    fi

    # Check prerequisites
    check_prereqs

    # Setup
    setup_network
    build_image
    ensure_proxy

    # Run in sandbox
    run_sandbox "$@"
}

main "$@"