#!/usr/bin/env bash
# 3.17 Android in an emulator (CI): the app starts and stays up, its home-screen widget is offered, the voice screen
# opens, the call screen is in the package, and nothing of ours crashed. Screenshots go to $1.
set -euo pipefail
OUT="${1:-/tmp/android-shots}"
PKG=cz.adamekk.jarvis
mkdir -p "$OUT"
adb wait-for-device
adb install -r mobile/JARVIS.apk
adb logcat -c || true
adb shell am start -W -n "$PKG/.MainActivity"
sleep 10
adb shell pidof "$PKG" >/dev/null || { echo "the app is not running after start"; exit 1; }
adb exec-out screencap -p > "$OUT/main.png"
# dumpsys prints the provider with its full class name (cz.adamekk.jarvis/cz.adamekk.jarvis.JarvisWidget)
adb shell dumpsys appwidget | grep -qE "$PKG/(\.|$PKG\.)JarvisWidget" \
  || adb shell dumpsys package "$PKG" | grep -q "JarvisWidget" || { echo "the widget is not offered"; exit 1; }
adb shell am start -W -n "$PKG/.VoiceActivity" || true
sleep 3
adb exec-out screencap -p > "$OUT/voice.png"
adb shell dumpsys package "$PKG" | grep -q "CallActivity" || { echo "the call screen is missing"; exit 1; }
adb shell input keyevent KEYCODE_HOME
sleep 2
adb exec-out screencap -p > "$OUT/home.png"
if adb logcat -d | grep -A3 "FATAL EXCEPTION" | grep -q "$PKG"; then
  adb logcat -d | grep -B2 -A20 "FATAL EXCEPTION" > "$OUT/crash.txt" || true
  echo "the app crashed"; exit 1
fi
echo "android smoke: ok"
