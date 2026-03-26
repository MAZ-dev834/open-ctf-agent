#!/usr/bin/env bash
set -u
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
TOOLS_DIR="${HOME}/tools"
mkdir -p "$BIN_DIR" "$TOOLS_DIR"
export PATH="$BIN_DIR:$PATH"

log() { printf "%s\n" "$*"; }

maybe_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return $?
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return $?
  fi
  log "[-] sudo not available for: $*"
  return 1
}

apt_install() {
  if ! command -v apt-get >/dev/null 2>&1; then
    log "[!] apt-get not found, skip apt installs"
    return 0
  fi
  maybe_sudo apt-get update -y >/dev/null 2>&1 || true
  maybe_sudo apt-get install -y "$@" || true
}

pip_install() {
  if ! command -v python3 >/dev/null 2>&1; then
    log "[!] python3 not found, skip pip install: $*"
    return 0
  fi
  python3 -m pip install --user -U "$@" || true
}

ensure_go() {
  if command -v go >/dev/null 2>&1; then
    return 0
  fi
  log "[*] Installing golang via apt"
  apt_install golang || true
}

go_install() {
  local pkg="$1"
  ensure_go
  if ! command -v go >/dev/null 2>&1; then
    log "[!] go not available, skip: $pkg"
    return 0
  fi
  GOBIN="$BIN_DIR" go install "${pkg}@latest" || true
}

git_clone_or_update() {
  local name="$1"
  local repo="$2"
  local dst="${TOOLS_DIR}/${name}"
  if [[ -d "$dst/.git" ]]; then
    (cd "$dst" && git pull --ff-only) || true
  else
    git clone --depth 1 "$repo" "$dst" || true
  fi
}

make_wrapper() {
  local name="$1"
  local target="$2"
  cat > "$BIN_DIR/$name" <<EOF
#!/usr/bin/env bash
exec "$target" "\$@"
EOF
  chmod +x "$BIN_DIR/$name"
}

log "[+] Installing baseline packages"
apt_install curl wget jq git unzip ripgrep ca-certificates python3 python3-pip

log "[+] Installing web scanners/fuzzers"
apt_install ffuf dirsearch nikto sqlmap || true
go_install "github.com/ffuf/ffuf"
go_install "github.com/tomnomnom/waybackurls"
go_install "github.com/lc/gau"
go_install "github.com/projectdiscovery/nuclei/v3/cmd/nuclei"
go_install "github.com/feroxbuster/feroxbuster"

log "[+] Installing Python tools"
pip_install httpie wfuzz requests beautifulsoup4 pyyaml tldextract jwt_tool pyjwt mitmproxy

log "[+] Installing linkfinder (git) + wrapper"
git_clone_or_update "linkfinder" "https://github.com/GerbenJavado/LinkFinder.git"
if [[ -f "$TOOLS_DIR/linkfinder/linkfinder.py" ]]; then
  pip_install -r "$TOOLS_DIR/linkfinder/requirements.txt"
  make_wrapper "linkfinder" "python3 $TOOLS_DIR/linkfinder/linkfinder.py"
fi

log "[+] Installing paramspider (git) + wrapper"
git_clone_or_update "paramspider" "https://github.com/devanshbatham/ParamSpider.git"
if [[ -f "$TOOLS_DIR/paramspider/paramspider.py" ]]; then
  pip_install -r "$TOOLS_DIR/paramspider/requirements.txt"
  make_wrapper "paramspider" "python3 $TOOLS_DIR/paramspider/paramspider.py"
fi

log "[+] Done. Ensure ${BIN_DIR} is in PATH for this shell."
