#!/bin/bash
# Finish an iOS root image after tools/mkiosroot.sh (its last steps use
# `install -o 272`, which current GNU coreutils rejects for a UID with no
# passwd entry), then apply tools/sweet-root-tweaks.py and fsck.
#   finish-iosroot.sh IMAGE
set -euo pipefail
img=$1
here=$(cd "$(dirname "$0")/.." && pwd)
mnt=$(mktemp -d)
fsck.hfsplus -f -y "$img" | grep -v 'Illegal name' || true
mount -t hfsplus -o loop,force "$img" "$mnt"
trap 'umount "$mnt" 2>/dev/null || true; rmdir "$mnt"' EXIT

# logd's log stores: owner _logd (272), modes, .migrated markers.
db="$mnt/private/var/db"
mkdir -p "$db/diagnostics/timesync" "$db/uuidtext"
chown 272:272 "$db/diagnostics" "$db/uuidtext" "$db/diagnostics/timesync"
chmod 0751 "$db/diagnostics"
chmod 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
	: > "$db/$d/.migrated"
	chown 272:272 "$db/$d/.migrated"
	chmod 0644 "$db/$d/.migrated"
done

# System keybag for the built-in AppleKeyStore stand-in (no passcode).
mkdir -p "$mnt/private/var/keybags"
chown 0:0 "$mnt/private/var/keybags"
chmod 0700 "$mnt/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' \
	> "$mnt/private/var/keybags/systembag.kb"
chown 0:0 "$mnt/private/var/keybags/systembag.kb"
chmod 0600 "$mnt/private/var/keybags/systembag.kb"

python3 "$here/sweet-root-tweaks.py" "$mnt"
test -f "$mnt/sbin/launchd"
test -f "$mnt/System/Library/CoreServices/SpringBoard.app/SpringBoard"
test -f "$mnt/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64"
df -h "$mnt"
sync
umount "$mnt"
trap - EXIT
rmdir "$mnt"
fsck.hfsplus -f -y "$img" | grep -v 'Illegal name' || true
fsck.hfsplus -f -n "$img"
