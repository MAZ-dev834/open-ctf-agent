#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <base_url> [wordlist]"
  exit 1
fi

BASE_URL="${1%/}"
WORDLIST="${2:-/usr/share/wordlists/dirb/common.txt}"

host_tag="$(echo "$BASE_URL" | sed -E 's#https?://##; s#[/:]#_#g')"
OUT_DIR="${OUT_DIR:-./workspace/active/web-recon-${host_tag}}"
TIMEOUT="${TIMEOUT:-15}"
RETRY="${RETRY:-2}"
UA="${UA:-Mozilla/5.0 (X11; Linux x86_64) CTF-Agent/1.0}"
COOKIE="${COOKIE:-}"
EXTRA_HEADER="${EXTRA_HEADER:-}"

mkdir -p "$OUT_DIR/raw" "$OUT_DIR/fuzz" "$OUT_DIR/report"

curl_opts=(--silent --show-error --location --max-time "$TIMEOUT" --retry "$RETRY" -A "$UA")
if [[ -n "$COOKIE" ]]; then
  curl_opts+=(--cookie "$COOKIE")
fi
if [[ -n "$EXTRA_HEADER" ]]; then
  curl_opts+=(-H "$EXTRA_HEADER")
fi

fetch() {
  local url="$1"
  local out="$2"
  curl "${curl_opts[@]}" "$url" -o "$out" || true
}

head_fetch() {
  local url="$1"
  local out="$2"
  curl "${curl_opts[@]}" -D "$out" -o /dev/null "$url" || true
}

echo "[+] Output directory: $OUT_DIR"
echo "[+] Base URL: $BASE_URL"

# Baseline fetches
fetch "$BASE_URL/" "$OUT_DIR/raw/index.html"
fetch "$BASE_URL/robots.txt" "$OUT_DIR/raw/robots.txt"
fetch "$BASE_URL/sitemap.xml" "$OUT_DIR/raw/sitemap.xml"
fetch "$BASE_URL/.well-known/security.txt" "$OUT_DIR/raw/security.txt"
head_fetch "$BASE_URL/" "$OUT_DIR/raw/headers.txt"

# Extract candidate links and script paths from index
if [[ -f "$OUT_DIR/raw/index.html" ]]; then
  rg -oN "(href|src)=['\"][^'\"]+['\"]" "$OUT_DIR/raw/index.html" \
    | sed -E "s/^(href|src)=['\"]//; s/['\"]$//" \
    | sort -u > "$OUT_DIR/report/asset_paths.txt" || true

  rg -oN "https?://[^\"'[:space:]]+" "$OUT_DIR/raw/index.html" \
    | sort -u > "$OUT_DIR/report/absolute_urls.txt" || true
fi

# Probe common endpoints quickly
cat > "$OUT_DIR/report/common_paths.txt" <<'PATHS'
/admin
/login
/register
/logout
/dashboard
/api
/api/v1
/debug
/graphql
/swagger
/swagger-ui
/.git/config
/.env
PATHS

while IFS= read -r p; do
  code="$(curl "${curl_opts[@]}" -o /dev/null -w "%{http_code}" "$BASE_URL$p" || echo 000)"
  printf "%s %s\n" "$code" "$p"
done < "$OUT_DIR/report/common_paths.txt" > "$OUT_DIR/report/common_paths_status.txt"

# Directory fuzz
if command -v ffuf >/dev/null 2>&1; then
  if [[ -f "$WORDLIST" ]]; then
    ffuf -u "$BASE_URL/FUZZ" -w "$WORDLIST" -mc all -fc 404 \
      -of json -o "$OUT_DIR/fuzz/ffuf_paths.json" || true
  else
    echo "[!] Wordlist not found: $WORDLIST" | tee "$OUT_DIR/report/warnings.txt"
  fi
else
  echo "[!] ffuf not installed, skip path fuzzing" | tee "$OUT_DIR/report/warnings.txt"
fi

# Optional vulnerability scan with nuclei
if command -v nuclei >/dev/null 2>&1; then
  nuclei -u "$BASE_URL" -silent -o "$OUT_DIR/fuzz/nuclei.txt" || true
fi

{
  echo "# Recon Summary"
  echo "base_url: $BASE_URL"
  echo "out_dir: $OUT_DIR"
  echo "headers: $OUT_DIR/raw/headers.txt"
  echo "common_path_status: $OUT_DIR/report/common_paths_status.txt"
  if [[ -f "$OUT_DIR/fuzz/ffuf_paths.json" ]]; then
    echo "ffuf: $OUT_DIR/fuzz/ffuf_paths.json"
  fi
  if [[ -f "$OUT_DIR/fuzz/nuclei.txt" ]]; then
    echo "nuclei: $OUT_DIR/fuzz/nuclei.txt"
  fi
} > "$OUT_DIR/report/summary.txt"

echo "[+] Recon finished. Summary: $OUT_DIR/report/summary.txt"
