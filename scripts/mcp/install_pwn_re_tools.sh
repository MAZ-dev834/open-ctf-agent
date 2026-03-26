#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install_pwn_re_tools.sh

Install local pwn/re tooling and activate pwndbg in ~/.gdbinit.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "[install_pwn_re_tools] unknown args: $*" >&2
  usage >&2
  exit 2
fi

sudo apt-get update
sudo apt-get install -y \
  gdb gdb-multiarch patchelf ruby-full \
  build-essential git curl wget unzip xz-utils file binutils

python3 -m pip install --user --upgrade pwntools ropper angr

gem install --user-install one_gadget
mkdir -p "$HOME/.local/bin"
ONE_GADGET_BIN="$(ruby -e 'print Gem.user_dir')/bin/one_gadget"
if [[ -x "$ONE_GADGET_BIN" ]]; then
  ln -sf "$ONE_GADGET_BIN" "$HOME/.local/bin/one_gadget"
fi

GEM_BIN_DIR="$(ruby -e 'print Gem.user_dir')/bin"
if ! grep -Fq "$GEM_BIN_DIR" "$HOME/.bashrc"; then
  printf '\n# Added by open-ctf-agent setup: one_gadget gem bin\nexport PATH="%s:$PATH"\n' "$GEM_BIN_DIR" >> "$HOME/.bashrc"
fi

mkdir -p "$HOME/.local/share"
if [[ ! -d "$HOME/.local/share/pwndbg/.git" ]]; then
  git clone --depth 1 https://github.com/pwndbg/pwndbg.git "$HOME/.local/share/pwndbg"
else
  git -C "$HOME/.local/share/pwndbg" pull --ff-only
fi
(cd "$HOME/.local/share/pwndbg" && ./setup.sh)

mkdir -p "$HOME/.local/share/gef"
curl -fsSL https://raw.githubusercontent.com/hugsy/gef/main/gef.py -o "$HOME/.local/share/gef/gef.py"

if [[ ! -d "$HOME/.local/share/peda/.git" ]]; then
  git clone --depth 1 https://github.com/longld/peda.git "$HOME/.local/share/peda"
else
  git -C "$HOME/.local/share/peda" pull --ff-only
fi

# Build/install radare2 locally under ~/.local
if [[ ! -d "$HOME/.local/src/radare2/.git" ]]; then
  mkdir -p "$HOME/.local/src"
  git clone --depth 1 https://github.com/radareorg/radare2.git "$HOME/.local/src/radare2"
else
  git -C "$HOME/.local/src/radare2" pull --ff-only
fi
(
  cd "$HOME/.local/src/radare2"
  ./sys/install.sh --prefix="$HOME/.local"
)

cat > "$HOME/.gdbinit" <<CFG
set pagination off
source $HOME/.local/share/pwndbg/gdbinit.py
CFG

echo "[+] pwn/re tool installation finished"
