#!/usr/bin/env bash
set -euo pipefail
# Use the official geographic mirror redirector in this disposable container.
printf 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch\n' > /etc/pacman.d/mirrorlist
pacman -Syu --noconfirm --needed base-devel python git curl desktop-file-utils
useradd --create-home builder
cp -a /inputs /build
chown -R builder:builder /build
runuser -u builder -- python /repo/.github/workflows/native-discord/build.py /build --epoch "$SOURCE_DATE_EPOCH"
# Install in this disposable Arch container only, including all runtime dependencies.
mapfile -t deps < <(python -c 'import sys;sys.path.insert(0,"/repo/.github/workflows/native-discord");from native_discord import DEPS;print("\n".join(DEPS))')
pacman -S --noconfirm --needed "${deps[@]}"
pacman -U --noconfirm /build/release/*.pkg.tar.zst
native-discord --help
native-discord -l
for c in stable ptb canary development; do
  test -x "/opt/native-discord/$c/updater_bootstrap"
  ldd "/opt/native-discord/$c/updater_bootstrap" > "/build/$c.ldd"
  if grep -q 'not found' "/build/$c.ldd"; then cat "/build/$c.ldd"; exit 1; fi
  desktop-file-validate "/usr/share/applications/discord-native-$c.desktop"
  test ! -e "/opt/native-discord/$c/postinst.sh"
done
pacman -Qkk native-discord-manager native-discord-{stable,ptb,canary,development}
# No app is started, no account is used, and no updater runs as root.
pacman -R --noconfirm native-discord-{stable,ptb,canary,development} native-discord-manager
cp -a /build/release/. /output/
