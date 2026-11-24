package cz.adamekk.jarvis;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Build;
import android.provider.ContactsContract;
import android.provider.Settings;
import android.telephony.SmsManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;

/**
 * 3.4 JARVIS phone link: settings, talking to the PC, and the phone actions (dial, SMS, WhatsApp, ring).
 * Everything here works without the web view, so the background service can use it while the app is closed.
 */
public final class JarvisLink {
    private JarvisLink() {}

    static final String CH_CALL = "jarvis_call_v1";
    static final String CH_LINK = "jarvis_link_v1";
    static final String CH_ACTION = "jarvis_action_v1";
    static final String CH_QUIET = "jarvis_quiet_v1";    // 3.17 "Zeptej se JARVISe" for the watch: shown without a sound
    static final int NOTIF_LINK = 7001;
    static final int NOTIF_CALL = 7002;

    // ---------- settings ----------
    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("jarvis_link", Context.MODE_PRIVATE);
    }

    static String base(Context c) { return prefs(c).getString("base", ""); }
    static String token(Context c) { return prefs(c).getString("token", ""); }
    static boolean enabled(Context c) { return prefs(c).getBoolean("enabled", false); }
    static boolean mirror(Context c) { return prefs(c).getBoolean("mirror", true); }

    // ---------- the PC ----------
    private static volatile long homeDownUntil;   // 3.12 the home address did not answer: use JARVIS Link for a while

    /** The address to use right now: home, or the JARVIS Link tunnel while home does not answer. */
    static String liveBase(Context c) {
        String base = base(c);
        boolean viaLink = base.startsWith(LinkProxy.base())
                || (LinkProxy.configured(c) && System.currentTimeMillis() < homeDownUntil);
        return viaLink && LinkProxy.start(c) ? LinkProxy.base() : base;
    }

    static String http(Context c, String method, String path, String body, int timeoutMs) throws Exception {
        String base = base(c);
        if (base.isEmpty()) throw new IllegalStateException("not paired");
        boolean viaLink = base.startsWith(LinkProxy.base());
        if (!viaLink && LinkProxy.configured(c) && System.currentTimeMillis() < homeDownUntil) viaLink = true;
        if (viaLink && LinkProxy.start(c)) return http(c, LinkProxy.base(), method, path, body, timeoutMs, 15000);
        try {
            return http(c, base, method, path, body, timeoutMs, LinkProxy.configured(c) ? 3000 : 8000);
        } catch (java.io.IOException e) {          // away from home (mobile data): the same request over JARVIS Link
            if (!LinkProxy.configured(c) || !LinkProxy.start(c)) throw e;
            homeDownUntil = System.currentTimeMillis() + 60000;
            return http(c, LinkProxy.base(), method, path, body, timeoutMs, 15000);
        }
    }

    private static String http(Context c, String base, String method, String path, String body, int timeoutMs, int connectMs) throws Exception {
        return http(c, base, method, path, body == null ? null : body.getBytes(StandardCharsets.UTF_8), "application/json; charset=utf-8", timeoutMs, connectMs);
    }

    /** 3.12 raw bytes (a voice recording) to the PC – at home, or over JARVIS Link when home does not answer. */
    static String httpBytes(Context c, String path, byte[] body, String type, int timeoutMs) throws Exception {
        String base = base(c);
        if (base.isEmpty()) throw new IllegalStateException("not paired");
        boolean viaLink = base.startsWith(LinkProxy.base());
        if (!viaLink && LinkProxy.configured(c) && System.currentTimeMillis() < homeDownUntil) viaLink = true;
        if (viaLink && LinkProxy.start(c)) return http(c, LinkProxy.base(), "POST", path, body, type, timeoutMs, 15000);
        try {
            return http(c, base, "POST", path, body, type, timeoutMs, LinkProxy.configured(c) ? 3000 : 8000);
        } catch (java.io.IOException e) {
            boolean unreachable = e instanceof java.net.ConnectException || e instanceof java.net.UnknownHostException
                    || e instanceof java.net.NoRouteToHostException
                    || (e instanceof java.net.SocketTimeoutException && String.valueOf(e.getMessage()).contains("connect"));
            if (!unreachable || !LinkProxy.configured(c) || !LinkProxy.start(c)) throw e;   // a slow answer is never asked twice
            homeDownUntil = System.currentTimeMillis() + 60000;
            return http(c, LinkProxy.base(), "POST", path, body, type, timeoutMs, 15000);
        }
    }

    private static String http(Context c, String base, String method, String path, byte[] body, String type, int timeoutMs, int connectMs) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(base + path).openConnection();
        con.setRequestMethod(method);
        con.setConnectTimeout(connectMs);
        con.setReadTimeout(timeoutMs);
        con.setRequestProperty("Authorization", "Bearer " + token(c));
        if (body != null) {
            con.setDoOutput(true);
            con.setFixedLengthStreamingMode(body.length);
            con.setRequestProperty("Content-Type", type);
            try (OutputStream os = con.getOutputStream()) { os.write(body); }
        }
        int code = con.getResponseCode();
        InputStream in = code < 400 ? con.getInputStream() : con.getErrorStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (in != null) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            in.close();
        }
        con.disconnect();
        if (code >= 400) throw new IllegalStateException("HTTP " + code);
        return out.toString("UTF-8");
    }

    /** 3.12 a file from the PC (home or JARVIS Link) into `dest`, at most `max` bytes. */
    static void download(Context c, String path, java.io.File dest, long max) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(liveBase(c) + path).openConnection();
        con.setConnectTimeout(8000);
        con.setReadTimeout(30000);
        con.setRequestProperty("Authorization", "Bearer " + token(c));
        int code = con.getResponseCode();
        if (code >= 400) { con.disconnect(); throw new IllegalStateException("HTTP " + code); }
        long got = 0;
        try (InputStream in = con.getInputStream(); OutputStream os = new java.io.FileOutputStream(dest)) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                got += n;
                if (got > max) throw new IllegalStateException("soubor je moc velký");
                os.write(buf, 0, n);
            }
        } finally {
            con.disconnect();
        }
    }

    static void ack(final Context c, final String id, final String state, final String detail) {
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject();
                o.put("id", id);
                o.put("state", state);
                o.put("detail", detail == null ? "" : detail);
                http(c, "POST", "/api/phone/ack", o.toString(), 15000);
            } catch (Exception ignored) { }
        }).start();
    }

    // ---------- contacts ----------
    static boolean has(Context c, String perm) {
        return c.checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED;
    }

    static boolean looksLikeNumber(String s) {
        return s != null && s.replaceAll("[\\s\\-()./]", "").matches("\\+?\\d{6,15}");
    }

    /** {name, number} for a name in the phone's contacts, the number itself, or null. Throws SecurityException without permission. */
    static String[] contact(Context c, String who) {
        if (looksLikeNumber(who)) return new String[] { who, who.replaceAll("[\\s\\-()./]", "") };
        if (!has(c, Manifest.permission.READ_CONTACTS)) throw new SecurityException("contacts");
        Uri uri = Uri.withAppendedPath(ContactsContract.CommonDataKinds.Phone.CONTENT_FILTER_URI, Uri.encode(who.trim()));
        String[] proj = { ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.IS_SUPER_PRIMARY };
        try (Cursor cur = c.getContentResolver().query(uri, proj, null, null,
                ContactsContract.CommonDataKinds.Phone.IS_SUPER_PRIMARY + " DESC")) {
            if (cur != null && cur.moveToFirst()) return new String[] { cur.getString(0), cur.getString(1) };
        }
        return null;
    }

    /** +420 for Czech numbers written without the country code (for WhatsApp links). */
    static String international(String number) {
        String d = number.replaceAll("[^\\d+]", "");
        if (d.startsWith("00")) d = "+" + d.substring(2);
        if (!d.startsWith("+") && d.length() == 9) d = "+420" + d;
        return d.replace("+", "");
    }

    // ---------- actions ----------
    /** "Zobrazovat přes jiné aplikace" lets the app open a screen from the background (dial at once, call screen). */
    static boolean canOpenScreens(Context c) {
        return Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(c);
    }

    /** Runs one command from the PC. Returns the state for the ack ("ringing" acks later from the call screen). */
    static String run(Context c, JSONObject cmd, boolean foreground) {
        String kind = cmd.optString("kind");
        foreground = foreground || canOpenScreens(c);
        try {
            switch (kind) {
                case "ring":
                    ring(c, cmd.optString("id"), cmd.optString("text"), cmd.optString("caller", "JARVIS"), foreground);
                    return "ringing";
                case "find":
                    FindPhone.start(c);
                    return "alarm";     // acked at once ("ringing" is only acked when a call is answered)
                case "find_stop":
                    FindPhone.stop(c);
                    return "done";
                case "dial": {
                    String[] ct = contact(c, cmd.optString("who"));
                    if (ct == null) return "notfound";
                    boolean direct = has(c, Manifest.permission.CALL_PHONE);
                    Intent i = new Intent(direct ? Intent.ACTION_CALL : Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(ct[1])));
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    if (foreground) { c.startActivity(i); return "calling"; }
                    actionNotification(c, "Zavolat: " + ct[0], ct[1] + " – klepni a JARVIS vytočí", i);
                    return "notified";
                }
                case "sms": {
                    String[] ct = contact(c, cmd.optString("to"));
                    if (ct == null) return "notfound";
                    if (!has(c, Manifest.permission.SEND_SMS)) return "permission";
                    SmsManager sms = Build.VERSION.SDK_INT >= 31 ? c.getSystemService(SmsManager.class) : SmsManager.getDefault();
                    ArrayList<String> parts = sms.divideMessage(cmd.optString("text"));
                    sms.sendMultipartTextMessage(ct[1], null, parts, null, null);
                    return "sent";
                }
                case "whatsapp": {
                    String[] ct = contact(c, cmd.optString("to"));
                    if (ct == null) return "notfound";
                    Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse("https://api.whatsapp.com/send?phone="
                            + international(ct[1]) + "&text=" + Uri.encode(cmd.optString("text"))));
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    if (foreground) { c.startActivity(i); return "opened"; }
                    actionNotification(c, "WhatsApp: " + ct[0], "Zpráva je připravená – klepni a odešli ji", i);
                    return "notified";
                }
                case "notify": {                // 3.12 you are away from the PC: what matters comes here
                    Intent open = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    JSONArray acts = cmd.optJSONArray("actions");
                    // 3.14 every notice gets "Odpovědět" (typed in the notification); its own buttons stay in front
                    noticeWithButtons(c, cmd.optString("title", "JARVIS"), cmd.optString("body", ""), open,
                            acts == null ? new JSONArray() : acts, cmd.optBoolean("quiet", false), cmd.optJSONArray("quick"));
                    return "shown";
                }
                case "widget": {                // 3.14 návrh 9: the widget kept fresh by this service, the app may be closed
                    android.content.SharedPreferences.Editor e = JarvisWidget.prefs(c).edit();
                    for (String k : new String[]{"status", "task", "song", "habits", "biz"}) {
                        if (cmd.has(k)) e.putString(k, cmd.optString(k, ""));
                    }
                    e.apply();
                    JarvisWidget.refresh(c);
                    return "shown";
                }
                case "mirror_ask": {             // 3.12 the PC wants to show this phone's screen: you allow it here
                    Intent ask = new Intent(c, MirrorConsentActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    if (foreground || canOpenScreens(c)) { c.startActivity(ask); return "asked"; }
                    actionNotification(c, "PC chce zobrazit obrazovku telefonu", "Klepni a povol sdílení obrazovky", ask);
                    return "notified";
                }
                case "mirror_stop":
                    if (MirrorService.running) MirrorService.stop(c);
                    return "done";
                case "morning": {                // 3.12 Ranní souhrn: the morning briefing with "Přehrát"
                    morningNotification(c, cmd.optString("title", "Ranní souhrn"), cmd.optString("text", ""));
                    if (cmd.optBoolean("autoplay") && headphonesOn(c) && canOpenScreens(c)) {
                        c.startActivity(new Intent(c, VoiceActivity.class).putExtra("say", cmd.optString("text", ""))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                        return "playing";
                    }
                    return "shown";
                }
                case "habits_left":              // 3.12 the evening habits: a "✓" per habit left, ticked right here
                    habitsNotification(c, cmd.optString("title", "Návyky na dnes"), cmd.optString("body", ""), cmd.optJSONArray("items"));
                    return "shown";
                case "confirm":                  // 3.12 a confirmation while you are away: Povolit / Zamítnout right here
                    confirmNotification(c, cmd.optString("cid"), cmd.optString("text"), cmd.optString("title", "JARVIS potřebuje potvrzení"),
                            cmd.optString("yes", "Povolit"));
                    return "shown";
                case "clip": {                   // 3.12 shared clipboard: what you copied on the PC
                    android.content.ClipboardManager cm = c.getSystemService(android.content.ClipboardManager.class);
                    if (cm == null) return "error";
                    String t = cmd.optString("text");
                    prefs(c).edit().putString("clip_from_pc", t.length() > 2000 ? t.substring(0, 2000) : t).apply();
                    cm.setPrimaryClip(android.content.ClipData.newPlainText("JARVIS", t));
                    return "done";
                }
                case "clip_image": {             // 3.12 a picture copied on the PC (a screenshot) → this phone's clipboard
                    java.io.File dir = new java.io.File(c.getCacheDir(), "clip");
                    if (!dir.isDirectory() && !dir.mkdirs()) return "error";
                    java.io.File[] old = dir.listFiles();
                    if (old != null) for (java.io.File f : old) f.delete();
                    java.io.File f = new java.io.File(dir, "schranka-" + System.currentTimeMillis() + ".png");
                    download(c, "/api/files/" + cmd.optString("aid"), f, 15 * 1024 * 1024);
                    Uri uri = androidx.core.content.FileProvider.getUriForFile(c, c.getPackageName() + ".fileprovider", f);
                    android.content.ClipboardManager cm = c.getSystemService(android.content.ClipboardManager.class);
                    if (cm == null) return "error";
                    cm.setPrimaryClip(android.content.ClipData.newUri(c.getContentResolver(), "JARVIS", uri));
                    prefs(c).edit().putString("clip_from_pc_img", uri.toString()).apply();
                    return "done";
                }
                case "notif_reply":            // 3.12 a reply written in the PC's notch, sent by the message's own app
                    return NotifMirror.reply(c, cmd.optString("key"), cmd.optString("text"));
                default:
                    return "unknown";
            }
        } catch (SecurityException e) {
            return "permission";
        } catch (Exception e) {
            return "error: " + e.getMessage();
        }
    }

    static void channels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT < 26 || nm == null) return;
        NotificationChannel call = new NotificationChannel(CH_CALL, "JARVIS volá", NotificationManager.IMPORTANCE_HIGH);
        call.setDescription("Když ti JARVIS zavolá (připomínka, důležitý e-mail…)");
        call.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
                new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        call.enableVibration(true);
        call.setVibrationPattern(new long[] { 0, 800, 600, 800, 600, 800 });
        call.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        call.setBypassDnd(true);
        nm.createNotificationChannel(call);
        NotificationChannel link = new NotificationChannel(CH_LINK, "Spojení s PC", NotificationManager.IMPORTANCE_MIN);
        link.setDescription("JARVIS běží na pozadí, aby ti mohl zavolat a poslat zprávu");
        link.setShowBadge(false);
        nm.createNotificationChannel(link);
        NotificationChannel act = new NotificationChannel(CH_ACTION, "Akce od JARVISe", NotificationManager.IMPORTANCE_HIGH);
        act.setDescription("Volání a zprávy, které JARVIS připravil");
        nm.createNotificationChannel(act);
        NotificationChannel quiet = new NotificationChannel(CH_QUIET, "Zeptej se z hodinek", NotificationManager.IMPORTANCE_LOW);
        quiet.setDescription("Tichá zpráva, na kterou odpovíš hlasem z telefonu nebo z hodinek Wear OS");
        quiet.setShowBadge(false);
        nm.createNotificationChannel(quiet);
    }

    static int piFlags() {
        return PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
    }

    static Notification.Builder builder(Context c, String channel) {
        return Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, channel) : new Notification.Builder(c);
    }

    /** From the background Android does not let an app open a screen; a notification the user taps does. */
    static void actionNotification(Context c, String title, String text, Intent target) {
        channels(c);
        PendingIntent pi = PendingIntent.getActivity(c, (int) (System.currentTimeMillis() & 0xffff), target, piFlags());
        Notification n = builder(c, CH_ACTION).setSmallIcon(android.R.drawable.sym_action_call).setContentTitle(title)
                .setContentText(text).setContentIntent(pi).setAutoCancel(true).setCategory(Notification.CATEGORY_MESSAGE).build();
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify((int) (System.currentTimeMillis() & 0xfffff), n);
    }

    /** 3.13 a notice from the PC with its buttons: a tap goes back to the PC as the same button in the notch would. */
    static void noticeWithButtons(Context c, String title, String text, Intent target, JSONArray acts) {
        noticeWithButtons(c, title, text, target, acts, false, null);
    }

    /** quiet = 3.17 without a sound (the "Zeptej se JARVISe" entry for the watch); quick = ready questions to tap or say. */
    static void noticeWithButtons(Context c, String title, String text, Intent target, JSONArray acts, boolean quiet, JSONArray quick) {
        channels(c);
        int nid = (int) (System.currentTimeMillis() & 0xfffff);
        PendingIntent pi = PendingIntent.getActivity(c, nid, target, piFlags());
        Notification.Builder b = builder(c, quiet ? CH_QUIET : CH_ACTION).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title)
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setContentIntent(pi).setAutoCancel(true)
                .setOnlyAlertOnce(quiet);
        if (Build.VERSION.SDK_INT >= 28) {        // 3.14 a message from "JARVIS": Android Auto and watches read it and offer a reply
            try {
                android.app.Person jarvis = new android.app.Person.Builder().setName("JARVIS").setKey("jarvis").build();
                android.app.Person me = new android.app.Person.Builder().setName("Já").setKey("me").build();
                b.setStyle(new Notification.MessagingStyle(me).setConversationTitle(title)
                        .addMessage(text, System.currentTimeMillis(), jarvis));
            } catch (Exception ignored) { }
        }
        for (int k = 0; k < acts.length() && k < 3; k++) {
            JSONObject a = acts.optJSONObject(k);
            if (a == null) continue;
            Intent i = new Intent(c, ConfirmReceiver.class).putExtra("notice_action", a.optString("action"))
                    .putExtra("notice_args", String.valueOf(a.optJSONObject("args") == null ? "{}" : a.optJSONObject("args")))
                    .putExtra("nid", nid);
            PendingIntent ap = PendingIntent.getBroadcast(c, nid * 4 + k, i, piFlags());
            b.addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(c, android.R.drawable.ic_menu_send),
                    a.optString("label", "Ok"), ap).build());
        }
        addReply(c, b, nid, quick);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(nid, b.build());
    }

    static final String REPLY_KEY = "jarvis_reply";

    /** 3.14 návrh 97: "Odpovědět" under every notice from the PC – typed right in the notification, sent to JARVIS. */
    static void addReply(Context c, Notification.Builder b, int nid) {
        addReply(c, b, nid, null);
    }

    /** choices: 3.17 ready answers a watch shows as buttons (and the phone as chips); speaking or typing still works. */
    static void addReply(Context c, Notification.Builder b, int nid, JSONArray choices) {
        if (Build.VERSION.SDK_INT < 24) return;
        try {
            android.app.RemoteInput.Builder rb = new android.app.RemoteInput.Builder(REPLY_KEY).setLabel("Napiš JARVISovi…");
            if (choices != null && choices.length() > 0) {
                int n = Math.min(choices.length(), 5);
                CharSequence[] cs = new CharSequence[n];
                for (int k = 0; k < n; k++) cs[k] = choices.optString(k, "");
                rb.setChoices(cs);
            }
            android.app.RemoteInput ri = rb.build();
            Intent i = new Intent(c, ConfirmReceiver.class).putExtra("notice_action", "ask").putExtra("notice_args", "{}")
                    .putExtra("reply", true).putExtra("nid", nid);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
            PendingIntent pi = PendingIntent.getBroadcast(c, nid * 4 + 3, i, flags);
            Notification.Action.Builder ab = new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(c, android.R.drawable.ic_menu_edit),
                    "Odpovědět", pi).addRemoteInput(ri);
            if (Build.VERSION.SDK_INT >= 28) ab.setSemanticAction(Notification.Action.SEMANTIC_ACTION_REPLY);
            b.addAction(ab.build());
        } catch (Exception ignored) { }
    }

    /** 3.12 Ranní souhrn: the whole text in the notice and "Přehrát" (JARVIS's voice in the visible JARVIS window). */
    static void morningNotification(Context c, String title, String text) {
        channels(c);
        PendingIntent play = PendingIntent.getActivity(c, 7301, new Intent(c, VoiceActivity.class).putExtra("say", text)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), piFlags());
        PendingIntent open = PendingIntent.getActivity(c, 7302, new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), piFlags());
        Notification n = builder(c, CH_ACTION).setSmallIcon(android.R.drawable.ic_menu_today).setContentTitle(title)
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setContentIntent(open).setAutoCancel(true)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(c, android.R.drawable.ic_media_play),
                        "Přehrát", play).build()).build();
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(7300, n);
    }

    /** Headphones (Bluetooth or cable) are connected right now. */
    static boolean headphonesOn(Context c) {
        android.media.AudioManager am = c.getSystemService(android.media.AudioManager.class);
        if (am == null) return false;
        for (android.media.AudioDeviceInfo d : am.getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS)) {
            int t = d.getType();
            if (t == android.media.AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || t == android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES
                    || t == android.media.AudioDeviceInfo.TYPE_WIRED_HEADSET || t == android.media.AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                    || (android.os.Build.VERSION.SDK_INT >= 26 && t == android.media.AudioDeviceInfo.TYPE_USB_HEADSET)
                    || (android.os.Build.VERSION.SDK_INT >= 31 && t == android.media.AudioDeviceInfo.TYPE_BLE_HEADSET)) return true;
        }
        return false;
    }

    static final int HABITS_NID = 7300;

    static void habitsNotification(Context c, String title, String text, org.json.JSONArray items) {
        channels(c);
        PendingIntent open = PendingIntent.getActivity(c, HABITS_NID, new Intent(Intent.ACTION_VIEW, Uri.parse("jarvis://open/habits"))
                .setPackage(c.getPackageName()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), piFlags());
        Notification.Builder b = builder(c, CH_ACTION).setSmallIcon(android.R.drawable.checkbox_on_background).setContentTitle(title)
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setContentIntent(open).setAutoCancel(true);
        for (int k = 0; items != null && k < Math.min(3, items.length()); k++) {
            org.json.JSONObject it = items.optJSONObject(k);
            if (it == null) continue;
            PendingIntent tick = PendingIntent.getBroadcast(c, HABITS_NID + 1 + k, new Intent(c, HabitReceiver.class)
                    .putExtra("id", it.optInt("id")).putExtra("nid", HABITS_NID), piFlags());
            b.addAction(new Notification.Action.Builder(null, "✓ " + it.optString("name"), tick).build());
        }
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(HABITS_NID, b.build());
    }

    static void confirmNotification(Context c, String cid, String text, String title, String yesLabel) {
        channels(c);
        int nid = 7100 + (cid.hashCode() & 0xff);
        PendingIntent yes = PendingIntent.getBroadcast(c, nid * 2, new Intent(c, ConfirmReceiver.class).putExtra("id", cid)
                .putExtra("approved", true).putExtra("nid", nid), piFlags());
        PendingIntent no = PendingIntent.getBroadcast(c, nid * 2 + 1, new Intent(c, ConfirmReceiver.class).putExtra("id", cid)
                .putExtra("approved", false).putExtra("nid", nid), piFlags());
        PendingIntent open = PendingIntent.getActivity(c, nid, new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), piFlags());
        Notification n = builder(c, CH_ACTION).setSmallIcon(android.R.drawable.ic_dialog_alert).setContentTitle(title)
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setContentIntent(open).setAutoCancel(true)
                .addAction(new Notification.Action.Builder(null, yesLabel, yes).build())
                .addAction(new Notification.Action.Builder(null, "Zamítnout", no).build()).build();
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(nid, n);
    }

    /** "JARVIS volá": full-screen call over the lock screen (or a ringing heads-up notification when the phone is in use). */
    static void ring(Context c, String id, String text, String caller, boolean openScreen) {
        channels(c);
        Intent screen = new Intent(c, CallActivity.class).putExtra("id", id).putExtra("text", text).putExtra("caller", caller)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent full = PendingIntent.getActivity(c, 1, screen, piFlags());
        PendingIntent answer = PendingIntent.getActivity(c, 2, new Intent(screen).putExtra("answer", true), piFlags());
        PendingIntent decline = PendingIntent.getBroadcast(c, 3, new Intent(c, CallActionReceiver.class).putExtra("id", id), piFlags());
        Notification n = builder(c, CH_CALL).setSmallIcon(android.R.drawable.sym_call_incoming)
                .setContentTitle(caller + " volá").setContentText("Přijmi a JARVIS ti řekne, co potřebuje.")
                .setCategory(Notification.CATEGORY_CALL).setPriority(Notification.PRIORITY_MAX).setOngoing(true)
                .setFullScreenIntent(full, true).setContentIntent(full)
                .addAction(new Notification.Action.Builder(null, "Odmítnout", decline).build())
                .addAction(new Notification.Action.Builder(null, "Přijmout", answer).build())
                .setVisibility(Notification.VISIBILITY_PUBLIC).build();
        n.flags |= Notification.FLAG_INSISTENT;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTIF_CALL, n);
        CallActivity.scheduleMissed(c, id, text);
        if (openScreen) {   // unlocked phone: Android would only show a heads-up; with the overlay permission the call screen opens
            try { c.startActivity(screen); } catch (Exception ignored) { }
        }
    }

    /** Battery level for "kolik má telefon baterky" (sent with every poll). */
    static String batteryQuery(Context c) {
        try {
            BatteryManager bm = c.getSystemService(BatteryManager.class);
            int level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
            boolean charging = Build.VERSION.SDK_INT >= 23 && bm.isCharging();
            return level >= 0 && level <= 100 ? "&battery=" + level + "&charging=" + (charging ? 1 : 0) : "";
        } catch (Exception e) {
            return "";
        }
    }

    /** 3.13 the phone was plugged in / unplugged: tell the PC at once (its notch shows "Telefon se nabíjí · 64 %"). */
    static void powerEvent(final Context c, final boolean charging) {
        new Thread(() -> {
            try {
                Thread.sleep(1500);                    // the level and the charging state settle a moment after the plug
                int level = -1;
                try {
                    BatteryManager bm = c.getSystemService(BatteryManager.class);
                    level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
                } catch (Exception ignored) { }
                if (level < 0 || level > 100) return;
                JSONObject o = new JSONObject();
                o.put("kind", "power");
                o.put("charging", charging);
                o.put("level", level);
                http(c, "POST", "/api/phone/event", o.toString(), 15000);
            } catch (Exception ignored) { }
        }).start();
    }

    /** 3.13 headphones on the phone / Do Not Disturb: a quiet line in the PC's notch. */
    static void deviceEvent(final Context c, final String kind, final boolean on, final String name) {
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject();
                o.put("kind", kind);
                o.put("on", on);
                o.put("name", name == null ? "" : name);
                http(c, "POST", "/api/phone/event", o.toString(), 15000);
            } catch (Exception ignored) { }
        }).start();
    }

    static JSONArray poll(Context c) throws Exception {
        // 3.12 battery: one request every 50 s while nothing happens (a command still arrives at once)
        String body = http(c, "GET", "/api/phone/poll?wait=50" + batteryQuery(c), null, 65000);
        return new JSONObject(body).optJSONArray("commands");
    }
}
