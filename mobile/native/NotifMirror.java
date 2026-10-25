package cz.adamekk.jarvis;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

/**
 * Tells JARVIS on the PC when a message or a call comes to the phone ("Píše vám máma na WhatsAppu…").
 * Android only runs this after you allow it yourself (Settings → Notification access); off again in the app.
 */
public class NotifMirror extends NotificationListenerService {
    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (!JarvisLink.mirror(this) || JarvisLink.base(this).isEmpty()) return;
        String pkg = sbn.getPackageName();
        if (pkg.equals(getPackageName())) return;
        Notification n = sbn.getNotification();
        boolean call = Notification.CATEGORY_CALL.equals(n.category);
        if ((n.flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;
        if (sbn.isOngoing() && !call) return;
        Bundle ex = n.extras;
        CharSequence title = ex.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence big = ex.getCharSequence(Notification.EXTRA_BIG_TEXT);
        CharSequence text = big != null ? big : ex.getCharSequence(Notification.EXTRA_TEXT);
        if (title == null && text == null) return;
        try {
            JSONObject o = new JSONObject();
            o.put("package", pkg);
            o.put("app", label(pkg));
            o.put("title", title == null ? "" : title.toString());
            o.put("text", text == null ? "" : text.toString());
            o.put("category", call ? "call" : (n.category == null ? "" : n.category));
            o.put("ts", sbn.getPostTime() / 1000.0);
            final String body = o.toString();
            new Thread(() -> {
                try { JarvisLink.http(this, "POST", "/api/phone/notification", body, 10000); } catch (Exception ignored) { }
            }).start();
        } catch (Exception ignored) { }
    }

    private String label(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            return pm.getApplicationLabel(ai).toString();
        } catch (Exception e) {
            return pkg;
        }
    }
}
