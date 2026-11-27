#!/bin/sh
set -eu
cd "$(dirname "$0")"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
install -Dm755 drive-desk "$stage/usr/share/drive-desk/drive-desk"
mkdir -p "$stage/usr/bin"
ln -s ../share/drive-desk/drive-desk "$stage/usr/bin/drive-desk"
for module in oauth.py cloud.py sync.py desktop_tools.py portable.py; do
    install -Dm644 "$module" "$stage/usr/share/drive-desk/$module"
done
for unit in drive-desk-sync.service drive-desk-sync.timer; do
    install -Dm644 "$unit" "$stage/usr/lib/systemd/user/$unit"
done
install -Dm644 FEATURES.md "$stage/usr/share/doc/drive-desk/FEATURES.md"
install -Dm644 nautilus_drive_desk.py "$stage/usr/share/nautilus-python/extensions/nautilus_drive_desk.py"
install -Dm644 drive-desk.desktop "$stage/usr/share/applications/drive-desk.desktop"
install -Dm644 LICENSE "$stage/usr/share/doc/drive-desk/copyright"
install -Dm644 README.md "$stage/usr/share/doc/drive-desk/README.md"
install -Dm644 control "$stage/DEBIAN/control"
dpkg-deb --root-owner-group --build "$stage" "${1:-drive-desk_0.4.0_all.deb}"
