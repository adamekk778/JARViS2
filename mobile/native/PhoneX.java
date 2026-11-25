package cz.adamekk.jarvis;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 3.20 Telefon + Hodinky (nápady 121–160), the phone's side:
 * Nerušit on the PC's word (130), the lock-screen line with the PC's volume (132, 133), a time-limited location share
 * (139 – you allow it with one tap here), a voice message shared to WhatsApp (16), the country and the month's mobile
 * data in the poll (134, 128).
 */
final class PhoneX {
    private PhoneX() { }

    static final int NOTIF_LOCK = 7010;
    static final int NOTIF_LOC_ASK = 7011;

    // ---------- (130) Nerušit
    static String dnd(Context c, boolean on) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null || Build.VERSION.SDK_INT < 23) return "error";
        if (!nm.isNotificationPolicyAccessGranted()) {
            JarvisLink.actionNotification(c, "JARVIS smí zapínat Nerušit?", "Klepni a povol JARVISovi přístup k režimu Nerušit",
                    new Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            return "permission";
        }
        nm.setInterruptionFilter(on ? NotificationManager.INTERRUPTION_FILTER_PRIORITY : NotificationManager.INTERRUPTION_FILTER_ALL);
        return on ? "on" : "off";
    }

    // ---------- (132, 133) the line on the lock screen + the PC's volume
    static String lockStatus(Context c, String line, boolean controls) {
        JarvisLink.channels(c);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return "error";
        if (line == null || line.isEmpty()) { nm.cancel(NOTIF_LOCK); return "hidden"; }
        PendingIntent open = PendingIntent.getActivity(c, NOTIF_LOCK, new Intent(c, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), JarvisLink.piFlags());
        Notification.Builder b = JarvisLink.builder(c, JarvisLink.CH_QUIET).setSmallIcon(android.R.drawable.ic_menu_today)
                .setContentTitle("JARVIS").setContentText(line).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
                .setShowWhen(false);
        if (Build.VERSION.SDK_INT >= 21) b.setVisibility(Notification.VISIBILITY_PUBLIC);
        if (controls) {
            String[][] acts = {{"vol_down", "−"}, {"mute", "Ztlumit PC"}, {"vol_up", "+"}};
            for (int k = 0; k < acts.length; k++) {
                Intent i = new Intent(c, PcControlReceiver.class).putExtra("action", acts[k][0]);
                PendingIntent pi = PendingIntent.getBroadcast(c, NOTIF_LOCK * 4 + k, i, JarvisLink.piFlags());
                b.addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(c,
                        android.R.drawable.ic_lock_silent_mode_off), acts[k][1], pi).build());
            }
        }
        nm.notify(NOTIF_LOCK, b.build());
        return "shown";
    }

    // ---------- (139) a time-limited location share: the PC asks, you allow it here
    static String locShare(Context c, String token, int minutes) {
        if (token == null || token.isEmpty() || minutes <= 0) {
            c.stopService(new Intent(c, LocShareService.class));
            return "stopped";
        }
        JarvisLink.channels(c);
        Intent svc = new Intent(c, LocShareService.class).putExtra("token", token).putExtra("minutes", minutes);
        PendingIntent go = Build.VERSION.SDK_INT >= 26
                ? PendingIntent.getForegroundService(c, NOTIF_LOC_ASK, svc, JarvisLink.piFlags())
                : PendingIntent.getService(c, NOTIF_LOC_ASK, svc, JarvisLink.piFlags());
        Notification n = JarvisLink.builder(c, JarvisLink.CH_ACTION).setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("Sdílet polohu " + minutes + " min?")
                .setContentText("JARVIS pošle tvou polohu na odkaz, který sdílíš. Po " + minutes + " min se to samo vypne.")
                .setAutoCancel(true)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(c,
                        android.R.drawable.ic_menu_send), "Sdílet", go).build())
                .build();
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTIF_LOC_ASK, n);
        return "asked";
    }

    // ---------- (16) a voice message: the recording from the PC, shared to WhatsApp (or any app you pick)
    static String voiceShare(Context c, JSONObject cmd, boolean foreground) throws Exception {
        String url = cmd.optString("url");
        if (!url.startsWith("http")) return "error";
        File dir = new File(c.getCacheDir(), "voice");
        if (!dir.isDirectory() && !dir.mkdirs()) return "error";
        File[] old = dir.listFiles();
        if (old != null) for (File f : old) f.delete();
        File f = new File(dir, "JARVIS-vzkaz" + (url.endsWith(".ogg") ? ".ogg" : ".mp3"));
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setConnectTimeout(8000);
        con.setReadTimeout(30000);
        try (InputStream in = con.getInputStream(); FileOutputStream out = new FileOutputStream(f)) {
            byte[] buf = new byte[16384];
            int n;
            long total = 0;
            while ((n = in.read(buf)) > 0) {
                total += n;
                if (total > 15L * 1024 * 1024) return "error";
                out.write(buf, 0, n);
            }
        }
        Uri uri = androidx.core.content.FileProvider.getUriForFile(c, c.getPackageName() + ".fileprovider", f);
        Intent send = new Intent(Intent.ACTION_SEND).setType("audio/*").putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        String to = cmd.optString("to");
        String[] ct = to.isEmpty() ? null : JarvisLink.contact(c, to);
        if (!to.isEmpty() && ct == null) return "notfound";
        if (ct != null) {
            send.setPackage("com.whatsapp");
            send.putExtra("jid", JarvisLink.international(ct[1]) + "@s.whatsapp.net");   // WhatsApp opens that chat
        }
        Intent open = Intent.createChooser(send, "Poslat hlasovou zprávu").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (ct != null && c.getPackageManager().resolveActivity(send, 0) != null) open = send.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (foreground) { c.startActivity(open); return "opened"; }
        JarvisLink.actionNotification(c, "Hlasová zpráva" + (ct != null ? " pro " + ct[0] : ""), "Klepni a pošli ji", open);
        return "notified";
    }

    // ---------- (134, 128) the country of the network and the month's mobile data, with each poll
    static String extraQuery(Context c) {
        StringBuilder q = new StringBuilder();
        try {
            android.telephony.TelephonyManager tm = c.getSystemService(android.telephony.TelephonyManager.class);
            String cc = tm == null ? "" : tm.getNetworkCountryIso();
            if (cc != null && cc.matches("[a-z]{2}")) q.append("&country=").append(cc);
        } catch (Exception ignored) { }
        long mb = monthMobileMb(c);
        if (mb >= 0) q.append("&mdata=").append(mb);
        return q.toString();
    }

    /** Mobile data used since the 1st of this month (MB), checked at most every 30 minutes. -1 = not allowed / unknown.
     *  Needs "Přístup k údajům o využití" for JARVIS (Android asks in Settings; it is optional). */
    static long monthMobileMb(Context c) {
        android.content.SharedPreferences p = JarvisLink.prefs(c);
        long now = System.currentTimeMillis();
        if (now - p.getLong("mdata_at", 0) < 30 * 60_000L) return p.getLong("mdata_mb", -1);
        long mb = -1;
        if (Build.VERSION.SDK_INT >= 23) {
            try {
                android.app.usage.NetworkStatsManager ns = c.getSystemService(android.app.usage.NetworkStatsManager.class);
                java.util.Calendar cal = java.util.Calendar.getInstance();
                cal.set(java.util.Calendar.DAY_OF_MONTH, 1);
                cal.set(java.util.Calendar.HOUR_OF_DAY, 0);
                cal.set(java.util.Calendar.MINUTE, 0);
                cal.set(java.util.Calendar.SECOND, 0);
                android.app.usage.NetworkStats.Bucket b = ns.querySummaryForDevice(
                        android.net.ConnectivityManager.TYPE_MOBILE, null, cal.getTimeInMillis(), now);
                if (b != null) mb = (b.getRxBytes() + b.getTxBytes()) / (1024 * 1024);
            } catch (Exception ignored) { mb = -1; }
        }
        p.edit().putLong("mdata_at", now).putLong("mdata_mb", mb).apply();
        return mb;
    }

    // ---------- PC controls from a tile / a notification button (122, 133)
    static void pcAction(final Context c, final String action, final android.content.BroadcastReceiver.PendingResult pr) {
        new Thread(() -> {
            try {
                JarvisLink.http(c, "POST", "/api/phone/action", new JSONObject().put("action", action).toString(), 10000);
            } catch (Exception ignored) {
            } finally {
                if (pr != null) pr.finish();
            }
        }, "jarvis-pc-action").start();
    }
}
