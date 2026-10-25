// Adds what JARVIS needs to the generated Android project (idempotent).
import { readFileSync, writeFileSync, existsSync, readdirSync, copyFileSync, mkdirSync } from "node:fs";

const manifestPath = "android/app/src/main/AndroidManifest.xml";
let m = readFileSync(manifestPath, "utf8");

const perms = [
  "android.permission.INTERNET",
  "android.permission.RECORD_AUDIO",
  "android.permission.MODIFY_AUDIO_SETTINGS",
  "android.permission.POST_NOTIFICATIONS",
  "android.permission.VIBRATE",
  "android.permission.ACCESS_NETWORK_STATE",
  "android.permission.USE_BIOMETRIC",
  // 3.4 phone link: JARVIS calls you, dials, SMS, background link, ring over the lock screen
  "android.permission.CALL_PHONE",
  "android.permission.READ_CONTACTS",
  "android.permission.SEND_SMS",
  "android.permission.FOREGROUND_SERVICE",
  "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
  "android.permission.USE_FULL_SCREEN_INTENT",
  "android.permission.WAKE_LOCK",
  "android.permission.RECEIVE_BOOT_COMPLETED",
  "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
  "android.permission.SYSTEM_ALERT_WINDOW",
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
// 3.4 phone link components
const components = `
        <service android:name=".LinkService" android:exported="false" android:foregroundServiceType="specialUse">
            <property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
                android:value="Spojení s asistentem JARVIS na vlastním PC: příchozí hovory od JARVISe, vytáčení a SMS na pokyn uživatele" />
        </service>
        <service android:name=".NotifMirror" android:exported="true" android:label="JARVIS – zprávy na PC"
            android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE">
            <intent-filter><action android:name="android.service.notification.NotificationListenerService" /></intent-filter>
        </service>
        <activity android:name=".CallActivity" android:exported="false" android:showWhenLocked="true" android:turnScreenOn="true"
            android:excludeFromRecents="true" android:launchMode="singleTop" android:taskAffinity=".call"
            android:theme="@android:style/Theme.DeviceDefault.NoActionBar.Fullscreen" />
        <receiver android:name=".CallActionReceiver" android:exported="false" />
        <receiver android:name=".BootReceiver" android:exported="true">
            <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED" /></intent-filter>
        </receiver>
`;
if (!m.includes(".LinkService")) m = m.replace("</application>", components + "    </application>");
const queries = `
    <queries>
        <package android:name="com.whatsapp" />
        <package android:name="com.whatsapp.w4b" />
        <intent><action android:name="android.intent.action.VIEW" /><data android:scheme="https" /></intent>
        <intent><action android:name="android.intent.action.DIAL" /></intent>
        <intent><action android:name="android.speech.tts.TTS_SERVICE" /></intent>
    </queries>
`;
if (!m.includes("<queries>")) m = m.replace("</manifest>", queries + "</manifest>");
writeFileSync(manifestPath, m);

// 3.4 native code (call screen, background link, notification mirror, plugin) → the app's package
const javaDir = "android/app/src/main/java/cz/adamekk/jarvis";
mkdirSync(javaDir, { recursive: true });
for (const f of readdirSync("native")) if (f.endsWith(".java")) copyFileSync(`native/${f}`, `${javaDir}/${f}`);

// keep the app's version in sync with package.json + CI run number
const gradlePath = "android/app/build.gradle";
if (existsSync(gradlePath)) {
  let g = readFileSync(gradlePath, "utf8");
  const run = Number(process.env.GITHUB_RUN_NUMBER || 1);
  g = g.replace(/versionCode \d+/, `versionCode ${run}`).replace(/versionName "[^"]*"/, `versionName "2.0.${run}"`);
  writeFileSync(gradlePath, g);
}
console.log("android project patched");
