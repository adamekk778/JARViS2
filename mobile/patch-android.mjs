// Adds what JARVIS needs to the generated Android project (idempotent).
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const manifestPath = "android/app/src/main/AndroidManifest.xml";
let m = readFileSync(manifestPath, "utf8");

const perms = [
  "android.permission.INTERNET",
  "android.permission.RECORD_AUDIO",
  "android.permission.MODIFY_AUDIO_SETTINGS",
  "android.permission.POST_NOTIFICATIONS",
  "android.permission.VIBRATE",
  "android.permission.ACCESS_NETWORK_STATE",
];
for (const p of perms) {
  if (!m.includes(`"${p}"`)) m = m.replace("</manifest>", `    <uses-permission android:name="${p}" />\n</manifest>`);
}
if (!m.includes("usesCleartextTraffic")) m = m.replace("<application", '<application android:usesCleartextTraffic="true"');

const share = `
            <intent-filter>
                <action android:name="android.intent.action.SEND" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="text/*" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="*/*" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND_MULTIPLE" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="*/*" />
            </intent-filter>`;
if (!m.includes("android.intent.action.SEND\"")) {
  // put the share filters inside MainActivity, right after its launcher filter
  m = m.replace(/(<category android:name="android.intent.category.LAUNCHER" \/>\s*<\/intent-filter>)/, `$1${share}`);
}
writeFileSync(manifestPath, m);

// keep the app's version in sync with package.json + CI run number
const gradlePath = "android/app/build.gradle";
if (existsSync(gradlePath)) {
  let g = readFileSync(gradlePath, "utf8");
  const run = Number(process.env.GITHUB_RUN_NUMBER || 1);
  g = g.replace(/versionCode \d+/, `versionCode ${run}`).replace(/versionName "[^"]*"/, `versionName "2.0.${run}"`);
  writeFileSync(gradlePath, g);
}
console.log("android project patched");
