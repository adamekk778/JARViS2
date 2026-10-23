#!/usr/bin/env bash
# Builds JARVIS.apk from ../web/dist. Needs Node 22, JDK 21 and the Android SDK (GitHub ubuntu runners have it).
set -euo pipefail
cd "$(dirname "$0")"
rm -rf www && cp -r ../web/dist www && cp www/mobile.html www/index.html
npm install --no-audit --no-fund
[ -d android ] || npx cap add android
npx capacitor-assets generate --android --iconBackgroundColor '#0a0c0f' --splashBackgroundColor '#0a0c0f' || echo "icon generation skipped"
npx cap sync android
node patch-android.mjs
mkdir -p ~/.android && cp debug.keystore ~/.android/debug.keystore   # stable signature → updates install over the old app
cd android
chmod +x gradlew
./gradlew assembleDebug --no-daemon --stacktrace
cp app/build/outputs/apk/debug/app-debug.apk ../JARVIS.apk
echo "built mobile/JARVIS.apk"
