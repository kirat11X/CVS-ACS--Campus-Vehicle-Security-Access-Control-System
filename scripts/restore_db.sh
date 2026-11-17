#!/usr/bin/env bash
# ==============================================================================
# scripts/restore_db.sh
# ==============================================================================
# Disaster Recovery & Database Restoration Utility for CVS-ACS (PostgreSQL)
#
# Validates SHA-256 checksum, verifies database connectivity, terminates
# active locks/connections, and restores database state from a compressed dump.
#
# Usage:
#   ./scripts/restore_db.sh /var/backups/cvs-acs/postgres/campus_security_20261117_030000.sql.gz
# ==============================================================================

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

log_info()  { echo -e "${CYAN}[INFO]${RESET} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${RESET} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${RESET} $1"; }
log_error() { echo -e "${RED}[ERROR]${RESET} $1"; }

if [ $# -lt 1 ]; then
    echo "Usage: $0 <path_to_backup.sql.gz> [--force]"
    exit 1
fi

BACKUP_FILE="$1"
FORCE=false
if [ "${2:-}" = "--force" ]; then
    FORCE=true
fi

if [ ! -f "$BACKUP_FILE" ]; then
    log_error "Backup file not found: $BACKUP_FILE"
    exit 1
fi

CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [ -f "$CHECKSUM_FILE" ]; then
    log_info "Verifying SHA-256 checksum integrity..."
    sha256sum -c "$CHECKSUM_FILE" || {
        log_error "SHA-256 Checksum validation FAILED! Archive may be corrupted."
        exit 1
    }
    log_ok "Checksum verified."
else
    log_warn "No .sha256 file found for $BACKUP_FILE. Proceeding with caution."
fi

CONTAINER_NAME="campus_postgres"
DB_NAME="${POSTGRES_DB:-campus_security}"
DB_USER="${POSTGRES_USER:-campus_admin}"
DB_PORT="${POSTGRES_PORT:-5433}"
DB_HOST="${POSTGRES_HOST:-127.0.0.1}"

if [ "$FORCE" = false ]; then
    echo -e "${YELLOW}${BOLD}WARNING:${RESET} This operation will overwrite all data in '${DB_NAME}'!"
    read -rp "Are you sure you want to proceed? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_info "Restoration aborted by user."
        exit 0
    fi
fi

log_info "Restoring database from $BACKUP_FILE into $DB_NAME..."

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    log_info "Restoring into Docker container '${CONTAINER_NAME}'..."
    # Terminate active client connections before restoring
    docker exec -t "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" || true

    gzip -dc "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"
elif command -v psql >/dev/null 2>&1; then
    log_info "Restoring via host psql against ${DB_HOST}:${DB_PORT}..."
    PGPASSWORD="${POSTGRES_PASSWORD:-campus_dev_pass}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" || true

    gzip -dc "$BACKUP_FILE" | PGPASSWORD="${POSTGRES_PASSWORD:-campus_dev_pass}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME"
else
    log_error "Neither running Docker container '${CONTAINER_NAME}' nor host 'psql' utility was found!"
    exit 1
fi

log_ok "Database successfully restored from backup!"
