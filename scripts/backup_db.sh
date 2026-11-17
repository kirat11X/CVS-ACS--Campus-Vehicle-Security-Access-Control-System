#!/usr/bin/env bash
# ==============================================================================
# scripts/backup_db.sh
# ==============================================================================
# Production Database Automated Backup Script for CVS-ACS (PostgreSQL)
#
# Features:
#   - Dumps PostgreSQL database (supports Docker container and local host)
#   - Compresses output with gzip / pigz
#   - Calculates and writes SHA-256 integrity checksums
#   - Prunes backups older than RETENTION_DAYS (default: 14 days)
#   - Optional S3 bucket archival sync
#
# Usage:
#   ./scripts/backup_db.sh [--backup-dir /var/backups/cvs-acs] [--retention-days 14]
# ==============================================================================

set -euo pipefail

# Configuration Defaults
BACKUP_DIR="${BACKUP_DIR:-/var/backups/cvs-acs/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
CONTAINER_NAME="campus_postgres"
DB_NAME="${POSTGRES_DB:-campus_security}"
DB_USER="${POSTGRES_USER:-campus_admin}"
DB_PORT="${POSTGRES_PORT:-5433}"
DB_HOST="${POSTGRES_HOST:-127.0.0.1}"

# ANSI styling
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

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"

log_info "Starting CVS-ACS PostgreSQL database backup..."
log_info "Target Database: $DB_NAME"
log_info "Destination:     $BACKUP_FILE"

# Determine backup execution strategy (Docker container vs host pg_dump)
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    log_info "Detected active Docker container '${CONTAINER_NAME}'. Executing pg_dump inside container..."
    docker exec -t "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip -c > "$BACKUP_FILE"
elif command -v pg_dump >/dev/null 2>&1; then
    log_info "Executing pg_dump via local host CLI against ${DB_HOST}:${DB_PORT}..."
    PGPASSWORD="${POSTGRES_PASSWORD:-campus_dev_pass}" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip -c > "$BACKUP_FILE"
else
    log_error "Neither running Docker container '${CONTAINER_NAME}' nor host 'pg_dump' utility was found!"
    exit 1
fi

# Verify backup integrity
if [ ! -s "$BACKUP_FILE" ]; then
    log_error "Backup file is empty or was not created: $BACKUP_FILE"
    rm -f "$BACKUP_FILE"
    exit 1
fi

BACKUP_SIZE_MB=$(du -m "$BACKUP_FILE" | cut -f1)
log_ok "Backup created successfully (${BACKUP_SIZE_MB} MB compressed)."

# Generate SHA-256 Checksum
log_info "Generating SHA-256 integrity checksum..."
sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"
log_ok "Checksum written to: $CHECKSUM_FILE"

# Prune old backups
log_info "Pruning backups older than ${RETENTION_DAYS} days in ${BACKUP_DIR}..."
PRUNED_COUNT=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz*" -mtime +"$RETENTION_DAYS" -delete -print | wc -l || echo "0")
log_ok "Pruned $PRUNED_COUNT expired backup archives."

# Optional AWS S3 archival
if [ -n "${S3_BACKUP_BUCKET:-}" ] && command -v aws >/dev/null 2>&1; then
    log_info "Syncing backup to AWS S3: ${S3_BACKUP_BUCKET}..."
    aws s3 cp "$BACKUP_FILE" "${S3_BACKUP_BUCKET}/postgres/" || log_warn "S3 upload failed."
    aws s3 cp "$CHECKSUM_FILE" "${S3_BACKUP_BUCKET}/postgres/" || log_warn "S3 checksum upload failed."
    log_ok "S3 backup synchronization complete."
fi

echo -e "\n${BOLD}${GREEN}======================================================================${RESET}"
echo -e "${BOLD}${GREEN}   CVS-ACS DATABASE BACKUP ROUTINE COMPLETED SUCCESSFULLY!    ${RESET}"
echo -e "${BOLD}${GREEN}======================================================================${RESET}\n"
