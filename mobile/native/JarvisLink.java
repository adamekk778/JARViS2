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
    static String http(Context c, String method, String path, String body, int timeoutMs) throws Exception {
        String base = base(c);
        if (base.isEmpty()) throw new IllegalStateException("not paired");
        HttpURLConnection con = (HttpURLConnection) new URL(base + path).openConnection();
        con.setRequestMethod(method);
        con.setConnectTimeout(8000);
        con.setReadTimeout(timeoutMs);
        con.setRequestProperty("Authorization", "Bearer " + token(c));
        if (body != null) {
            con.setDoOutput(true);
            con.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream os = con.getOutputStream()) { os.write(body.getBytes(StandardCharsets.UTF_8)); }
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

    static JSONArray poll(Context c) throws Exception {
        String body = http(c, "GET", "/api/phone/poll?wait=25", null, 40000);
        return new JSONObject(body).optJSONArray("commands");
    }
}
