#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <base_url>"
  exit 1
fi

BASE_URL="${1%/}"
DOMAIN="$(echo "$BASE_URL" | sed -E 's#https?://##; s#/.*##')"
TAG="$(echo "$DOMAIN" | sed -E 's#[/:]#_#g')"
OUT_DIR="${OUT_DIR:-./workspace/active/web-js-${TAG}}"
TIMEOUT="${TIMEOUT:-15}"
RETRY="${RETRY:-2}"
UA="${UA:-Mozilla/5.0 (X11; Linux x86_64) CTF-Agent/1.0}"

mkdir -p "$OUT_DIR/raw" "$OUT_DIR/js" "$OUT_DIR/report"

curl_opts=(--silent --show-error --location --max-time "$TIMEOUT" --retry "$RETRY" -A "$UA")

echo "[+] Base URL: $BASE_URL"
echo "[+] Output directory: $OUT_DIR"

curl "${curl_opts[@]}" "$BASE_URL/" -o "$OUT_DIR/raw/index.html" || true

if [[ -f "$OUT_DIR/raw/index.html" ]]; then
  rg -oN "(href|src)=['\"][^'\"]+['\"]" "$OUT_DIR/raw/index.html" \
    | sed -E "s/^(href|src)=['\"]//; s/['\"]$//" \
    | sort -u > "$OUT_DIR/report/asset_paths.txt" || true
fi

touch "$OUT_DIR/report/urls_all.txt"

if command -v gau >/dev/null 2>&1; then
  gau --subs "$DOMAIN" | sort -u >> "$OUT_DIR/report/urls_all.txt" || true
fi

if command -v waybackurls >/dev/null 2>&1; then
  echo "$DOMAIN" | waybackurls | sort -u >> "$OUT_DIR/report/urls_all.txt" || true
fi

if [[ -f "$OUT_DIR/report/asset_paths.txt" ]]; then
  while IFS= read -r path; do
    if [[ "$path" =~ ^https?:// ]]; then
      echo "$path"
    elif [[ "$path" =~ ^// ]]; then
      echo "https:${path}"
    else
      echo "${BASE_URL}${path}"
    fi
  done < "$OUT_DIR/report/asset_paths.txt" >> "$OUT_DIR/report/urls_all.txt"
fi

sort -u "$OUT_DIR/report/urls_all.txt" -o "$OUT_DIR/report/urls_all.txt"

rg -i "\\.js(\\?|$)" "$OUT_DIR/report/urls_all.txt" | sort -u > "$OUT_DIR/report/js_urls.txt" || true

fetch_js() {
  local url="$1"
  local fname
  fname="$(echo "$url" | sed -E 's#https?://##; s#[/?&=]#_#g')"
  if [[ -z "$fname" ]]; then
    return
  fi
  curl "${curl_opts[@]}" "$url" -o "$OUT_DIR/js/${fname}.js" || true
}

if [[ -s "$OUT_DIR/report/js_urls.txt" ]]; then
  while IFS= read -r js; do
    fetch_js "$js"
  done < "$OUT_DIR/report/js_urls.txt"
fi

touch "$OUT_DIR/report/endpoints.txt"

LF=""
if command -v linkfinder >/dev/null 2>&1; then
  LF="linkfinder"
elif command -v linkfinder.py >/dev/null 2>&1; then
  LF="linkfinder.py"
fi

if [[ -n "$LF" ]]; then
  for jsf in "$OUT_DIR"/js/*.js; do
    [[ -f "$jsf" ]] || continue
    $LF -i "$jsf" -o cli 2>/dev/null | rg -o "https?://[^\"'[:space:]]+|/[^\"'[:space:]]+" || true
  done | sort -u >> "$OUT_DIR/report/endpoints.txt"
fi

rg -o "https?://[^\"'[:space:]]+|/[^\"'[:space:]]+" "$OUT_DIR/js"/*.js 2>/dev/null \
  | sort -u >> "$OUT_DIR/report/endpoints.txt" || true

sort -u "$OUT_DIR/report/endpoints.txt" -o "$OUT_DIR/report/endpoints.txt"

if command -v paramspider >/dev/null 2>&1; then
  paramspider -d "$DOMAIN" -o "$OUT_DIR/report/paramspider.txt" >/dev/null 2>&1 || true
fi

{
  echo "# JS Recon Summary"
  echo "base_url: $BASE_URL"
  echo "domain: $DOMAIN"
  echo "urls_all: $OUT_DIR/report/urls_all.txt"
  echo "js_urls: $OUT_DIR/report/js_urls.txt"
  echo "endpoints: $OUT_DIR/report/endpoints.txt"
  if [[ -f "$OUT_DIR/report/paramspider.txt" ]]; then
    echo "paramspider: $OUT_DIR/report/paramspider.txt"
  fi
} > "$OUT_DIR/report/summary.txt"

echo "[+] JS recon finished. Summary: $OUT_DIR/report/summary.txt"
