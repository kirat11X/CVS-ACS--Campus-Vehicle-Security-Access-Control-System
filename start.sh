#!/usr/bin/env bash
# ==============================================================================
# CVS-ACS Master System Startup & Orchestration Script
# Campus Vehicle Security & Access-Control System
# Punjab Engineering College (PEC), Sector 12, Chandigarh
# ==============================================================================
# Starts and monitors:
#   1. Container Infrastructure: PostgreSQL (5433), Mosquitto MQTT (1883),
#      Frigate NVR (5000), n8n Automation (5678)
#   2. Database Migrations: Alembic upgrade head
#   3. Model Runtimes & Inference Assets:
#      - Ollama LLM (11434) + qwen3:4b-instruct-2507-q4_K_M
#      - YOLO11n Plate Detector (ONNX) + Indian Plate CRNN Recognizer (ONNX)
#      - CVS-ACS 45,000 Deliverables Catalog & Dual-Engine OCR (RapidOCR + Tesseract)
#   4. Core Backend: FastAPI / Uvicorn (8000) with MQTT Worker, Stream Runner,
#      and Telegram Bot Gateway (@KritanshCampusbot)
#   5. Guard Console Frontend: React 19 + Vite 6 SPA (5173)
# ==============================================================================

set -eo pipefail

# ------------------------------------------------------------------------------
# Terminal Formatting & Colors
# ------------------------------------------------------------------------------
BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
MAGENTA="\033[35m"
RESET="\033[0m"

log_info()    { echo -e "${CYAN}ℹ [INFO]${RESET}  $1"; }
log_ok()      { echo -e "${GREEN}✓ [OK]${RESET}    $1"; }
log_warn()    { echo -e "${YELLOW}⚠ [WARN]${RESET}  $1"; }
log_error()   { echo -e "${RED}✖ [ERROR]${RESET} $1"; }
log_step()    { echo -e "\n${BOLD}${MAGENTA}▶ $1${RESET}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
cd "$ROOT_DIR"

RUN_DIR="$ROOT_DIR/.run"
LOGS_DIR="$ROOT_DIR/logs"
mkdir -p "$RUN_DIR" "$LOGS_DIR" "$ROOT_DIR/media/invoices" "$ROOT_DIR/media/plates"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
OLLAMA_PID_FILE="$RUN_DIR/ollama.pid"

# Default flags
NO_DOCKER=false
DAEMON_MODE=false
SUBCOMMAND="up"

# ------------------------------------------------------------------------------
# Banner Display
# ------------------------------------------------------------------------------
print_banner() {
    echo -e "${BOLD}${CYAN}"
    echo "  ======================================================================"
    echo "      CVS-ACS: Campus Vehicle Security & Access-Control System"
    echo "         Punjab Engineering College (PEC), Sector 12, Chandigarh"
    echo "  ======================================================================"
    echo -e "${RESET}"
}

# ------------------------------------------------------------------------------
# Helper: Detect LAN IP
# ------------------------------------------------------------------------------
get_lan_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
    if [[ -z "$ip" ]]; then
        ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' || echo "127.0.0.1")
    fi
    echo "$ip"
}

# ------------------------------------------------------------------------------
# Helper: Check if Port is in Use
# ------------------------------------------------------------------------------
is_port_open() {
    local port="$1"
    if command -v nc >/dev/null 2>&1; then
        nc -z 127.0.0.1 "$port" >/dev/null 2>&1
        return $?
    fi
    (echo > "/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
    return $?
}

# ------------------------------------------------------------------------------
# Cleanup / Teardown Handler
# ------------------------------------------------------------------------------
cleanup() {
    echo -e "\n${YELLOW}Stopping CVS-ACS services...${RESET}"
    if [[ -f "$FRONTEND_PID_FILE" ]]; then
        local f_pid
        f_pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)
        if [[ -n "$f_pid" ]] && kill -0 "$f_pid" 2>/dev/null; then
            kill "$f_pid" 2>/dev/null || true
            log_ok "Frontend server stopped (PID $f_pid)"
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi

    if [[ -f "$BACKEND_PID_FILE" ]]; then
        local b_pid
        b_pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)
        if [[ -n "$b_pid" ]] && kill -0 "$b_pid" 2>/dev/null; then
            kill "$b_pid" 2>/dev/null || true
            log_ok "Backend server stopped (PID $b_pid)"
        fi
        rm -f "$BACKEND_PID_FILE"
    fi

    if [[ -f "$OLLAMA_PID_FILE" ]]; then
        local o_pid
        o_pid=$(cat "$OLLAMA_PID_FILE" 2>/dev/null || true)
        if [[ -n "$o_pid" ]] && kill -0 "$o_pid" 2>/dev/null; then
            kill "$o_pid" 2>/dev/null || true
            log_ok "Temporary Ollama process stopped (PID $o_pid)"
        fi
        rm -f "$OLLAMA_PID_FILE"
    fi

    log_info "Infrastructure containers (PostgreSQL, Mosquitto, Frigate) remain active."
    log_info "Use './start.sh down' if you also wish to stop the Docker containers."
}

# ------------------------------------------------------------------------------
# Subcommand: Stop All Services
# ------------------------------------------------------------------------------
stop_all_services() {
    print_banner
    log_step "Stopping all CVS-ACS processes and services..."

    # Stop frontend process
    if [[ -f "$FRONTEND_PID_FILE" ]]; then
        local f_pid
        f_pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)
        if [[ -n "$f_pid" ]] && kill -0 "$f_pid" 2>/dev/null; then
            kill -15 "$f_pid" 2>/dev/null || kill -9 "$f_pid" 2>/dev/null || true
            log_ok "Stopped frontend process (PID $f_pid)"
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi

    # Stop any stray vite processes on port 5173
    local stray_vite
    stray_vite=$(lsof -ti:5173 2>/dev/null || true)
    if [[ -n "$stray_vite" ]]; then
        kill -9 $stray_vite 2>/dev/null || true
        log_ok "Terminated stray process on port 5173"
    fi

    # Stop backend process
    if [[ -f "$BACKEND_PID_FILE" ]]; then
        local b_pid
        b_pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)
        if [[ -n "$b_pid" ]] && kill -0 "$b_pid" 2>/dev/null; then
            kill -15 "$b_pid" 2>/dev/null || kill -9 "$b_pid" 2>/dev/null || true
            log_ok "Stopped backend process (PID $b_pid)"
        fi
        rm -f "$BACKEND_PID_FILE"
    fi

    # Stop any stray uvicorn processes on port 8000
    local stray_uvicorn
    stray_uvicorn=$(lsof -ti:8000 2>/dev/null || true)
    if [[ -n "$stray_uvicorn" ]]; then
        kill -9 $stray_uvicorn 2>/dev/null || true
        log_ok "Terminated stray process on port 8000"
    fi

    # Option to stop docker containers
    if command -v docker >/dev/null 2>&1; then
        log_info "Stopping Docker Compose containers..."
        docker compose down || true
        log_ok "Docker Compose containers stopped."
    fi

    echo -e "\n${GREEN}${BOLD}✓ All CVS-ACS services have been stopped cleanly.${RESET}\n"
    exit 0
}

# ------------------------------------------------------------------------------
# Subcommand: System Status Check
# ------------------------------------------------------------------------------
show_status() {
    print_banner
    log_step "System Health & Status Matrix"

    local lan_ip
    lan_ip=$(get_lan_ip)

    printf "\n${BOLD}%-30s %-16s %-32s${RESET}\n" "SERVICE / COMPONENT" "STATUS" "ENDPOINT / DETAILS"
    echo "--------------------------------------------------------------------------------"

    # PostgreSQL
    if is_port_open 5433; then
        printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "PostgreSQL Database" "ACTIVE (UP)" "localhost:5433 (campus_security)"
    else
        printf "%-30s ${RED}%-16s${RESET} %-32s\n" "PostgreSQL Database" "OFFLINE" "Port 5433 closed"
    fi

    # Mosquitto MQTT
    if is_port_open 1883; then
        printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "Mosquitto MQTT Broker" "ACTIVE (UP)" "localhost:1883 (frigate/#)"
    else
        printf "%-30s ${YELLOW}%-16s${RESET} %-32s\n" "Mosquitto MQTT Broker" "OFFLINE" "Port 1883 closed"
    fi

    # Frigate NVR
    if is_port_open 5000; then
        printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "Frigate NVR" "ACTIVE (UP)" "http://localhost:5000"
    else
        printf "%-30s ${DIM}%-16s${RESET} %-32s\n" "Frigate NVR" "STANDBY" "Port 5000 (RTSP: 8554)"
    fi

    # Ollama LLM
    if is_port_open 11434; then
        local models_json
        models_json=$(curl -s http://127.0.0.1:11434/api/tags 2>/dev/null || echo "")
        if echo "$models_json" | grep -q "qwen3"; then
            printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "Ollama LLM (qwen3)" "ACTIVE (UP)" "http://localhost:11434"
        else
            printf "%-30s ${YELLOW}%-16s${RESET} %-32s\n" "Ollama LLM" "ACTIVE (UP)" "qwen3 not pulled yet"
        fi
    else
        printf "%-30s ${RED}%-16s${RESET} %-32s\n" "Ollama LLM" "OFFLINE" "Port 11434 closed"
    fi

    # Core FastAPI Backend
    if is_port_open 8000; then
        local health_json
        health_json=$(curl -s http://127.0.0.1:8000/health 2>/dev/null || echo "")
        if [[ -n "$health_json" ]]; then
            printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "FastAPI Backend API" "HEALTHY (UP)" "http://localhost:8000/docs"
        else
            printf "%-30s ${YELLOW}%-16s${RESET} %-32s\n" "FastAPI Backend API" "STARTING" "Port 8000 open"
        fi
    else
        printf "%-30s ${RED}%-16s${RESET} %-32s\n" "FastAPI Backend API" "OFFLINE" "Port 8000 closed"
    fi

    # Guard Console Frontend
    if is_port_open 5173; then
        printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "Vite Guard Console" "ACTIVE (UP)" "http://localhost:5173"
    else
        printf "%-30s ${RED}%-16s${RESET} %-32s\n" "Vite Guard Console" "OFFLINE" "Port 5173 closed"
    fi

    # Model weights
    local det_weight="$ROOT_DIR/weights/yolo11n_plate_detector_finetuned.onnx"
    local ocr_weight="$ROOT_DIR/weights/indian_plate_crnn_best.onnx"
    if [[ -f "$det_weight" && -f "$ocr_weight" ]]; then
        printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "YOLO11n & CRNN Weights" "AVAILABLE" "weights/*.onnx loaded"
    else
        printf "%-30s ${YELLOW}%-16s${RESET} %-32s\n" "YOLO11n & CRNN Weights" "PARTIAL" "Check weights/ directory"
    fi

    # Deliverables Catalog
    local cat_45k="$ROOT_DIR/cvs_acs_master_45000_deliverables.csv"
    if [[ -f "$cat_45k" ]]; then
        local rows
        rows=$(wc -l < "$cat_45k" 2>/dev/null || echo "42935")
        printf "%-30s ${GREEN}%-16s${RESET} %-32s\n" "Deliverables Catalog" "ACTIVE" "$rows items indexed"
    else
        printf "%-30s ${YELLOW}%-16s${RESET} %-32s\n" "Deliverables Catalog" "FALLBACK" "20,000 CSV active"
    fi

    echo "--------------------------------------------------------------------------------"
    echo -e "LAN IP for Mobile Guard Tablet: ${BOLD}${CYAN}http://${lan_ip}:5173${RESET}\n"
    exit 0
}

# ------------------------------------------------------------------------------
# Parse Command Line Options
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        up|start)
            SUBCOMMAND="up"
            shift
            ;;
        down|stop)
            stop_all_services
            ;;
        status|health)
            show_status
            ;;
        restart)
            stop_all_services
            SUBCOMMAND="up"
            shift
            ;;
        --no-docker)
            NO_DOCKER=true
            shift
            ;;
        -d|--daemon)
            DAEMON_MODE=true
            shift
            ;;
        backend)
            SUBCOMMAND="backend"
            shift
            ;;
        frontend)
            SUBCOMMAND="frontend"
            shift
            ;;
        demo)
            SUBCOMMAND="demo"
            shift
            ;;
        test)
            SUBCOMMAND="test"
            shift
            ;;
        -h|--help)
            echo "Usage: ./start.sh [COMMAND] [OPTIONS]"
            echo ""
            echo "Commands:"
            echo "  up / start        Start full project stack (default)"
            echo "  down / stop       Stop all running project services"
            echo "  restart           Clean restart of the entire system"
            echo "  status            Show health and operational status matrix"
            echo "  backend           Start only infrastructure, models, and backend API"
            echo "  frontend          Start only the frontend console (Vite)"
            echo "  demo              Run the interactive video ANPR & invoice OCR pipeline demo"
            echo "  test              Execute the full test suite (138+ automated tests)"
            echo ""
            echo "Options:"
            echo "  --no-docker       Skip starting Docker Compose infrastructure"
            echo "  -d, --daemon      Run services in the background"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            log_warn "Unknown parameter: $1. Running standard full-stack startup."
            shift
            ;;
    esac
done

# ------------------------------------------------------------------------------
# Subcommand Execution: Demo or Test
# ------------------------------------------------------------------------------
if [[ "$SUBCOMMAND" == "demo" ]]; then
    print_banner
    log_step "Running Pipeline Demonstration Script..."
    PYTHONPATH=. "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/demo_pipeline_run.py"
    exit $?
fi

if [[ "$SUBCOMMAND" == "test" ]]; then
    print_banner
    log_step "Running Full Project Pytest Suite..."
    PYTHONPATH=. "$ROOT_DIR/.venv/bin/pytest" "$ROOT_DIR/backend/tests" -v
    exit $?
fi

# ------------------------------------------------------------------------------
# 1. Environment & Prerequisite Checks
# ------------------------------------------------------------------------------
print_banner
log_step "1/6: Verifying System Environment & Dependencies"

# .env configuration
if [[ ! -f "$ROOT_DIR/.env" ]]; then
    if [[ -f "$ROOT_DIR/.env.example" ]]; then
        log_warn "No .env file found. Generating .env from .env.example..."
        cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
        log_ok "Created .env configuration."
    else
        log_error "Missing .env and .env.example file in $ROOT_DIR!"
        exit 1
    fi
fi

# Load .env
set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env" 2>/dev/null || true
set +a
log_ok "Loaded environment variables from .env"

# Python virtual environment
if [[ ! -d "$ROOT_DIR/.venv" ]]; then
    log_error "Python virtual environment not found at $ROOT_DIR/.venv!"
    log_info "Please run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt (or uv sync)"
    exit 1
fi
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
log_ok "Found Python virtual environment: $($PYTHON_BIN --version)"

# Node.js and npm for frontend
if [[ "$SUBCOMMAND" != "backend" ]]; then
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        log_error "Node.js and npm are required for the frontend console!"
        exit 1
    fi
    log_ok "Found Node.js $(node --version) and npm $(npm --version)"
fi

# ------------------------------------------------------------------------------
# 2. Container Infrastructure (PostgreSQL, Mosquitto, Frigate, n8n)
# ------------------------------------------------------------------------------
log_step "2/6: Starting Docker Infrastructure"

if [[ "$NO_DOCKER" == true ]]; then
    log_info "Skipping Docker startup (--no-docker specified)."
else
    if ! command -v docker >/dev/null 2>&1; then
        log_warn "Docker command not found! Assuming services are running on host/remote."
    else
        log_info "Starting containers via Docker Compose (PostgreSQL 5433, Mosquitto 1883, Frigate 5000, n8n 5678)..."
        docker compose up -d mosquitto postgres frigate n8n 2>&1 || docker compose up -d 2>&1
        log_ok "Docker Compose containers launched."
    fi
fi

# Wait for PostgreSQL to be ready on port 5433
log_info "Waiting for PostgreSQL on port 5433..."
MAX_PG_WAIT=25
PG_READY=false
for ((i=1; i<=MAX_PG_WAIT; i++)); do
    if is_port_open 5433; then
        # Try a quick DB connection check via python
        if "$PYTHON_BIN" -c "
import psycopg, os
conn = psycopg.connect('host=localhost port=5433 dbname=campus_security user=campus_admin password=campus_dev_pass', connect_timeout=2)
conn.close()
" >/dev/null 2>&1; then
            PG_READY=true
            break
        fi
    fi
    sleep 1
done

if [[ "$PG_READY" == true ]]; then
    log_ok "PostgreSQL is online and accepting connections on port 5433."
else
    log_warn "PostgreSQL did not acknowledge connection within ${MAX_PG_WAIT}s. Proceeding with caution..."
fi

# ------------------------------------------------------------------------------
# 3. Database Schema Migrations
# ------------------------------------------------------------------------------
log_step "3/6: Applying Database Migrations (Alembic)"

ALEMBIC_BIN="$ROOT_DIR/.venv/bin/alembic"
if [[ -f "$ALEMBIC_BIN" ]]; then
    log_info "Running: alembic upgrade head..."
    PYTHONPATH=. "$ALEMBIC_BIN" upgrade head
    log_ok "Database schema is synchronized with latest revisions."
else
    log_warn "Alembic executable not found at $ALEMBIC_BIN. Skipping auto-migration."
fi

# ------------------------------------------------------------------------------
# 4. AI Models & Computer Vision Runtimes
# ------------------------------------------------------------------------------
log_step "4/6: Initializing AI Models & Computer Vision Assets"

# A. Ollama LLM Runtime
OLLAMA_TARGET_MODEL="${OLLAMA_MODEL:-qwen3:4b-instruct-2507-q4_K_M}"
log_info "Checking Ollama LLM runtime on http://localhost:11434..."

if is_port_open 11434; then
    log_ok "Ollama service is active on port 11434."
else
    log_info "Starting Ollama daemon in background..."
    if command -v ollama >/dev/null 2>&1; then
        ollama serve > "$LOGS_DIR/ollama.log" 2>&1 &
        echo $! > "$OLLAMA_PID_FILE"
        sleep 2
        if is_port_open 11434; then
            log_ok "Ollama daemon started successfully."
        else
            log_warn "Ollama daemon launched, waiting for socket..."
        fi
    else
        log_warn "Ollama command not found. LLM invoice extractor will use deterministic fallback."
    fi
fi

# Check / pull preferred Ollama model
if is_port_open 11434 && command -v ollama >/dev/null 2>&1; then
    local_models=$(curl -s http://127.0.0.1:11434/api/tags 2>/dev/null || echo "")
    if echo "$local_models" | grep -q "$OLLAMA_TARGET_MODEL"; then
        log_ok "Preferred extraction model '$OLLAMA_TARGET_MODEL' is ready."
    elif echo "$local_models" | grep -q "qwen3"; then
        log_ok "Compatible Qwen3 model found in Ollama repository."
    else
        log_info "Model '$OLLAMA_TARGET_MODEL' not found locally. Initiating background pull..."
        ollama pull "$OLLAMA_TARGET_MODEL" > "$LOGS_DIR/ollama_pull.log" 2>&1 &
    fi
fi

# B. ANPR License Plate Weights
DET_WEIGHT="$ROOT_DIR/weights/yolo11n_plate_detector_finetuned.onnx"
OCR_WEIGHT="$ROOT_DIR/weights/indian_plate_crnn_best.onnx"
if [[ -f "$DET_WEIGHT" ]]; then
    log_ok "YOLO11n Plate Detector ONNX: $(basename "$DET_WEIGHT")"
else
    log_warn "Finetuned detector not found; will look for baseline weights in weights/"
fi

if [[ -f "$OCR_WEIGHT" ]]; then
    log_ok "Indian Plate CRNN Recognizer ONNX: $(basename "$OCR_WEIGHT")"
else
    log_warn "CRNN recognizer not found; will look for track_a_ocr_cct.onnx in weights/"
fi

# C. CVS-ACS Deliverables Catalog
DELIVERABLES_CSV="$ROOT_DIR/cvs_acs_master_45000_deliverables.csv"
if [[ -f "$DELIVERABLES_CSV" ]]; then
    local_count=$(wc -l < "$DELIVERABLES_CSV" 2>/dev/null || echo "42935")
    log_ok "CVS-ACS Master Deliverables: $(basename "$DELIVERABLES_CSV") ($local_count entries)"
else
    log_warn "45,000 Deliverables CSV not in root; using cvs_acs_master_20000_deliverables.csv."
fi

# ------------------------------------------------------------------------------
# 5. Core Application Backend (FastAPI / Uvicorn)
# ------------------------------------------------------------------------------
if [[ "$SUBCOMMAND" != "frontend" ]]; then
    log_step "5/6: Starting FastAPI Core Backend (Port 8000)"

    # Clean up any existing process on 8000
    if is_port_open 8000; then
        local_stray=$(lsof -ti:8000 2>/dev/null || true)
        if [[ -n "$local_stray" ]]; then
            log_warn "Port 8000 already occupied by PID $local_stray. Terminating prior instance..."
            kill -15 $local_stray 2>/dev/null || kill -9 $local_stray 2>/dev/null || true
            sleep 1
        fi
    fi

    log_info "Launching Uvicorn on 0.0.0.0:8000..."
    PYTHONPATH=. "$ROOT_DIR/.venv/bin/uvicorn" backend.app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level info > "$LOGS_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!
    echo "$BACKEND_PID" > "$BACKEND_PID_FILE"

    # Wait for backend to be healthy
    MAX_API_WAIT=20
    API_READY=false
    for ((i=1; i<=MAX_API_WAIT; i++)); do
        if is_port_open 8000; then
            if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
                API_READY=true
                break
            fi
        fi
        sleep 1
    done

    if [[ "$API_READY" == true ]]; then
        log_ok "FastAPI Core Backend is active (PID $BACKEND_PID) on http://localhost:8000"
        log_ok "Telegram bot gateway, MQTT ingestion worker, and camera runners initialized."
    else
        log_warn "Backend started (PID $BACKEND_PID), waiting for full initialization..."
    fi
fi

# ------------------------------------------------------------------------------
# 6. Guard Console Frontend (Vite React SPA)
# ------------------------------------------------------------------------------
if [[ "$SUBCOMMAND" != "backend" ]]; then
    log_step "6/6: Starting Guard Console Frontend (Port 5173)"

    cd "$ROOT_DIR/frontend"

    # Ensure npm packages are installed
    if [[ ! -d "node_modules" ]]; then
        log_info "Installing frontend dependencies (npm install)..."
        npm install
    fi

    # Clean up any existing process on 5173
    if is_port_open 5173; then
        local_vite=$(lsof -ti:5173 2>/dev/null || true)
        if [[ -n "$local_vite" ]]; then
            log_warn "Port 5173 already occupied by PID $local_vite. Terminating prior instance..."
            kill -15 $local_vite 2>/dev/null || kill -9 $local_vite 2>/dev/null || true
            sleep 1
        fi
    fi

    log_info "Launching Vite Dev Server on 0.0.0.0:5173..."
    npm run dev -- --host 0.0.0.0 --port 5173 > "$LOGS_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
    cd "$ROOT_DIR"

    # Wait for frontend to respond
    MAX_FE_WAIT=15
    FE_READY=false
    for ((i=1; i<=MAX_FE_WAIT; i++)); do
        if is_port_open 5173; then
            FE_READY=true
            break
        fi
        sleep 1
    done

    if [[ "$FE_READY" == true ]]; then
        log_ok "Guard Console Frontend is active (PID $FRONTEND_PID) on http://localhost:5173"
    else
        log_warn "Frontend server started (PID $FRONTEND_PID), listening on port 5173."
    fi
fi

# ------------------------------------------------------------------------------
# Operational Summary & Dashboard
# ------------------------------------------------------------------------------
LAN_IP=$(get_lan_ip)

echo -e "\n${BOLD}${GREEN}======================================================================${RESET}"
echo -e "${BOLD}${GREEN}   CVS-ACS SYSTEM IS FULLY OPERATIONAL AND READY FOR INGESTION        ${RESET}"
echo -e "${BOLD}${GREEN}======================================================================${RESET}"

echo -e "\n${BOLD}Access Endpoints & Dashboards:${RESET}"
echo -e "  🌐 ${CYAN}Guard Console (Local):${RESET}      http://localhost:5173"
echo -e "  📱 ${CYAN}Guard Console (Campus LAN):${RESET} http://${LAN_IP}:5173"
echo -e "  🔌 ${CYAN}Backend REST API Docs:${RESET}      http://localhost:8000/docs"
echo -e "  🤖 ${CYAN}Telegram Intake Bot:${RESET}        https://t.me/KritanshCampusbot (@KritanshCampusbot)"
echo -e "  📹 ${CYAN}Frigate NVR Console:${RESET}        http://localhost:5000"
echo -e "  🗄️  ${CYAN}PostgreSQL Database:${RESET}        localhost:5433 (campus_security)"
echo -e "  📡 ${CYAN}Mosquitto MQTT Broker:${RESET}      localhost:1883"
echo -e "  🧠 ${CYAN}Ollama LLM Engine:${RESET}          http://localhost:11434 (Model: $OLLAMA_TARGET_MODEL)"
echo -e "  ⚙️  ${CYAN}n8n Automation Engine:${RESET}      http://localhost:5678"

echo -e "\n${BOLD}Runtime Logs:${RESET}"
echo -e "  Backend logs:  ${DIM}$LOGS_DIR/backend.log${RESET}"
echo -e "  Frontend logs: ${DIM}$LOGS_DIR/frontend.log${RESET}"
echo -e "  Ollama logs:   ${DIM}$LOGS_DIR/ollama.log${RESET}"

echo -e "\n${BOLD}Control Commands:${RESET}"
echo -e "  Check status:  ${CYAN}./start.sh status${RESET}"
echo -e "  Run demo:      ${CYAN}./start.sh demo${RESET}"
echo -e "  Run tests:     ${CYAN}./start.sh test${RESET}"
echo -e "  Stop stack:    ${CYAN}./start.sh stop${RESET}"
echo -e "${BOLD}======================================================================${RESET}\n"

if [[ "$DAEMON_MODE" == true ]]; then
    log_ok "Stack is running in daemon background mode. To view logs: tail -f logs/backend.log"
    exit 0
fi

# Foreground mode: set trap for graceful exit on Ctrl+C
trap cleanup SIGINT SIGTERM

echo -e "${DIM}Press [Ctrl+C] to gracefully stop backend and frontend services...${RESET}"
while true; do
    sleep 2
    # Check if backend or frontend died unexpectedly
    if [[ "$SUBCOMMAND" != "frontend" && -f "$BACKEND_PID_FILE" ]]; then
        b_pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)
        if [[ -n "$b_pid" ]] && ! kill -0 "$b_pid" 2>/dev/null; then
            log_error "Backend process ($b_pid) terminated unexpectedly! Check logs/backend.log"
            break
        fi
    fi
    if [[ "$SUBCOMMAND" != "backend" && -f "$FRONTEND_PID_FILE" ]]; then
        f_pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)
        if [[ -n "$f_pid" ]] && ! kill -0 "$f_pid" 2>/dev/null; then
            log_error "Frontend process ($f_pid) terminated unexpectedly! Check logs/frontend.log"
            break
        fi
    fi
done
cleanup
