#!/usr/bin/env bash
# Install into this checkout and register Automater for the current desktop user.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

usage() {
    echo "Usage: ./install.sh [--no-system-packages]"
    echo "Installs runtime packages and a per-user application-menu shortcut."
    echo "Use --no-system-packages when dependencies are already installed."
}
system_packages=1
case "${1:-}" in
    --no-system-packages) system_packages=0 ;;
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi
if [[ "$(uname -s)" != Linux ]]; then
    echo "Automater supports Linux only." >&2
    exit 1
fi
if (( EUID == 0 )); then
    echo "Run ./install.sh as your regular desktop user, without sudo." >&2
    echo "It requests sudo only for system packages." >&2
    exit 1
fi

if (( system_packages )); then
    if ! command -v sudo >/dev/null; then
        echo "sudo is unavailable. Ask an administrator to install the libraries in docs/INSTALL.md, then use --no-system-packages." >&2
        exit 1
    fi
    # Identify the distribution, rather than guessing from an installed helper.
    distro_id=""; distro_like=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        distro_id="${ID:-}"; distro_like="${ID_LIKE:-}"
    fi
    case " $distro_id $distro_like " in
        *" debian "*|*" ubuntu "*)
            sudo apt-get update
            sudo apt-get install -y git ca-certificates python3 python3-venv python3-pip python3-dev build-essential linux-libc-dev \
                libegl1 libopengl0 libgl1 libglib2.0-0 fontconfig libfreetype6 libdbus-1-3 \
                libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
                libxcb-xinerama0 libxcb1 libx11-xcb1 libxcb-shape0 libxcb-randr0 libxcb-render0 \
                libxcb-render-util0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 \
                libwayland-client0 libwayland-cursor0 libwayland-egl1 desktop-file-utils
            ;;
        *" fedora "*)
            sudo dnf install -y git ca-certificates python3 python3-pip python3-devel gcc kernel-headers \
                mesa-libEGL libglvnd-opengl mesa-libGL libxkbcommon libxkbcommon-x11 libxcb \
                xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil \
                fontconfig freetype glib2 dbus-libs libwayland-client libwayland-cursor libwayland-egl \
                dejavu-sans-fonts desktop-file-utils
            ;;
        *)
            echo "Automatic system-package setup currently covers Debian/Ubuntu and Fedora." >&2
            echo "For this distribution, install the libraries in docs/INSTALL.md, then run ./install.sh --no-system-packages." >&2
            exit 1
            ;;
    esac
fi

echo "Installing Automater's tested Python runtime…"
./start.sh --doctor > /dev/null
echo "Creating your application-menu shortcut…"
.venv/bin/python -m automater.desktop --checkout "$PWD"
echo
echo "Automater is installed. Search for Automater in your application menu."
echo "For a safe preview: ./start.sh --demo"
echo "For recording/playback, open Devices → Input access help."
echo "Keep this folder in place: the menu shortcut launches the app from here."
