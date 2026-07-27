#!/usr/bin/env bash
set -euo pipefail

KEY="${1:?module key required}"
DIR="${2:?module dir required}"
PORT="${3:?port required}"

WORKSPACE="/workspace"
REPO="${WORKSPACE}/druppie"
MOD_DIR="${REPO}/druppie/mcp-servers/${DIR}"
VENV="${WORKSPACE}/.venvs/${KEY}"
BAKED="/opt/venvs/${KEY}"
DEP_DIR="${WORKSPACE}/.dep-hashes"
REQ="${MOD_DIR}/requirements.txt"
SHA_FILE="${DEP_DIR}/mcp-${KEY}.sha"

mkdir -p "${DEP_DIR}"

if [ ! -d "${VENV}" ] && [ -d "${BAKED}" ]; then
  echo "[module-dev] seeding venv from baked snapshot"
  cp -a "${BAKED}" "${VENV}"
fi

if [ ! -d "${VENV}" ]; then
  echo "[module-dev] creating fresh venv"
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install --no-cache-dir --upgrade pip
fi

if [ -f "${REQ}" ]; then
  CUR=$(sha256sum "${REQ}" | cut -d' ' -f1)
  OLD=$(cat "${SHA_FILE}" 2>/dev/null || echo "")
  if [ "${CUR}" != "${OLD}" ]; then
    echo "[module-dev] deps changed — pip install"
    "${VENV}/bin/pip" install --no-cache-dir -r "${REQ}" && echo "${CUR}" > "${SHA_FILE}"
  else
    echo "[module-dev] deps unchanged — reusing venv"
  fi
fi

echo "[module-dev] starting ${KEY} on 0.0.0.0:${PORT} from ${DIR}"
cd "${MOD_DIR}"
exec "${VENV}/bin/python" -m uvicorn server:app \
  --host 0.0.0.0 --port "${PORT}" \
  --reload --reload-dir "${MOD_DIR}"
