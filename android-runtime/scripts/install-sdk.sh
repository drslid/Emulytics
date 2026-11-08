#!/usr/bin/env bash
set -euo pipefail

sdk_root="${ANDROID_HOME:?ANDROID_HOME is required}"
mkdir -p "$sdk_root/cmdline-tools" "$sdk_root/system-images/android-29/google_apis"
while read -r digest archive; do
  [[ -z "$digest" || "$digest" == \#* ]] && continue
  [[ "$digest" =~ ^[a-f0-9]{64}$ && "$archive" == https://dl.google.com/android/repository/* ]] || exit 1
  curl --fail --location --retry 3 --proto '=https' "$archive" -o /tmp/android-package.zip
  printf '%s  %s\n' "$digest" /tmp/android-package.zip | sha256sum --check -
  case "$archive" in
    *commandlinetools-*)
      unzip -q /tmp/android-package.zip -d "$sdk_root/cmdline-tools"
      mv "$sdk_root/cmdline-tools/cmdline-tools" "$sdk_root/cmdline-tools/latest"
      ;;
    *x86_64-29_r13.zip)
      unzip -q /tmp/android-package.zip -d "$sdk_root/system-images/android-29/google_apis"
      ;;
    *) unzip -q /tmp/android-package.zip -d "$sdk_root" ;;
  esac
  rm /tmp/android-package.zip
done < /opt/emulytix/sdk-packages.sha256

test -x "$sdk_root/emulator/emulator"
test -x "$sdk_root/platform-tools/adb"
grep -Fxq 'Pkg.Revision=13' "$sdk_root/system-images/android-29/google_apis/x86_64/source.properties"
# Unlike older SDK packages, the emulator needs local repository metadata.
cat > "$sdk_root/emulator/package.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<common:repository xmlns:common="http://schemas.android.com/repository/android/common/02" xmlns:generic="http://schemas.android.com/repository/android/generic/02" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <localPackage path="emulator" obsolete="false">
    <type-details xsi:type="generic:genericDetailsType"/>
    <revision><major>37</major><minor>2</minor><micro>12</micro></revision>
    <display-name>Android Emulator</display-name>
  </localPackage>
</common:repository>
XML
printf 'no\n' | avdmanager create avd --name emulytix-build-check \
  --package 'system-images;android-29;google_apis;x86_64'
avdmanager delete avd --name emulytix-build-check
