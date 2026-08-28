#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${ROOT}/data/orbit/source/gps_ops_latest_omm.csv}"
FORCE="${FORCE:-0}"
URL='https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV'

if [[ -e "${OUT}" && "${FORCE}" != "1" ]]; then
  echo "Refusing to overwrite existing snapshot: ${OUT}" >&2
  echo "Set FORCE=1 only when you intentionally need a refreshed GPS-OPS update." >&2
  exit 2
fi
mkdir -p "$(dirname "${OUT}")"
TMP="${OUT}.tmp.$$"
trap 'rm -f "${TMP}"' EXIT
curl --fail --location --retry 2 --output "${TMP}" "${URL}"
grep -q '^OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION' "${TMP}" || {
  echo "Downloaded response is not the expected OMM CSV" >&2
  exit 1
}
mv "${TMP}" "${OUT}"
trap - EXIT
sha256sum "${OUT}"
echo "Downloaded once to ${OUT}. Respect CelesTrak's update/usage policy; do not poll this script."
