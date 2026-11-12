package cz.adamekk.jarvis;

import android.Manifest;
import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import org.json.JSONObject;

/** 3.4 the phone side of JARVIS for the web app: switch the link on/off, permissions, and run commands in the foreground. */
@CapacitorPlugin(name = "JarvisPhone", permissions = {
        @Permission(alias = "phone", strings = { Manifest.permission.CALL_PHONE, Manifest.permission.READ_CONTACTS, Manifest.permission.SEND_SMS }),
})
public class JarvisPhonePlugin extends Plugin {
    static JarvisPhonePlugin instance;
    static JSObject pendingReply;

    @Override
    public void load() {
        instance = this;
    }

    static void reply(String callId) {
        JSObject d = new JSObject();
        d.put("callId", callId == null ? "" : callId);
        if (instance != null && instance.hasListeners("reply")) instance.notifyListeners("reply", d, true);
        else pendingReply = d;
    }

    @PluginMethod
    public void configure(PluginCall call) {
        android.content.SharedPreferences.Editor e = JarvisLink.prefs(getContext()).edit();
        if (call.hasOption("base")) e.putString("base", call.getString("base", ""));
        if (call.hasOption("token")) e.putString("token", call.getString("token", ""));
        if (call.hasOption("enabled")) e.putBoolean("enabled", Boolean.TRUE.equals(call.getBoolean("enabled", false)));
        if (call.hasOption("mirror")) e.putBoolean("mirror", Boolean.TRUE.equals(call.getBoolean("mirror", true)));
        if (call.hasOption("island")) {                   // 3.12 the notch on the phone: needs the background link
            boolean on = Boolean.TRUE.equals(call.getBoolean("island", false));
            e.putBoolean("island", on);
            if (on) e.putBoolean("enabled", true);
        }
        if (call.hasOption("tapdrop")) {                  // 3.12 knock to send the newest photo: needs the background link
            boolean on = Boolean.TRUE.equals(call.getBoolean("tapdrop", false));
            e.putBoolean("tapdrop", on);
            if (on) e.putBoolean("enabled", true);
        }
        if (call.hasOption("link")) {                     // 3.12 JARVIS Link: how to reach the PC from outside (+ its fingerprint)
            String info = call.getString("link", "");
            e.putString("link_info", info == null ? "" : info);
        }
        e.apply();
        try {
            if (JarvisLink.enabled(getContext()) && !JarvisLink.base(getContext()).isEmpty()) LinkService.start(getContext());
            else LinkService.stop(getContext());
        } catch (Exception ex) {
            call.reject("Spojení na pozadí se nepodařilo zapnout: " + ex.getMessage());
            return;
        }
        status(call);
    }

    @PluginMethod
    public void status(PluginCall call) {
        JSObject r = new JSObject();
        r.put("running", LinkService.running);
        r.put("enabled", JarvisLink.enabled(getContext()));
        r.put("mirror", JarvisLink.mirror(getContext()));
        r.put("tapdrop", TapDrop.enabled(getContext()));
        r.put("island", PhoneIsland.enabled(getContext()));
        if (PhoneIsland.enabled(getContext())) PhoneIsland.start(getContext());   // allowed the overlay just now → show it
        r.put("photos", TapDrop.canReadPhotos(getContext()));
        r.put("phone", JarvisLink.has(getContext(), Manifest.permission.CALL_PHONE)
                && JarvisLink.has(getContext(), Manifest.permission.READ_CONTACTS)
                && JarvisLink.has(getContext(), Manifest.permission.SEND_SMS));
        String listeners = Settings.Secure.getString(getContext().getContentResolver(), "enabled_notification_listeners");
        r.put("notifAccess", listeners != null && listeners.contains(new ComponentName(getContext(), NotifMirror.class).flattenToString()));
        NotificationManager nm = getContext().getSystemService(NotificationManager.class);
        r.put("fullScreen", Build.VERSION.SDK_INT < 34 || (nm != null && nm.canUseFullScreenIntent()));
        PowerManager pm = getContext().getSystemService(PowerManager.class);
        r.put("overlay", JarvisLink.canOpenScreens(getContext()));
        r.put("battery", Build.VERSION.SDK_INT < 23 || (pm != null && pm.isIgnoringBatteryOptimizations(getContext().getPackageName())));
        r.put("versionCode", ApkUpdate.versionCode(getContext()));
        call.resolve(r);
    }

    /** 3.12 JARVIS Link: start the encrypted tunnel to the PC; the app then talks to the PC through {base}. */
    @PluginMethod
    public void linkStart(PluginCall call) {
        new Thread(() -> {
            JSObject r = new JSObject();
            boolean ok = LinkProxy.start(getContext());
            r.put("ok", ok);
            r.put("base", ok ? LinkProxy.base() : "");
            r.put("route", LinkProxy.lastRoute);
            call.resolve(r);
        }, "jarvis-link-start").start();
    }

    /** 3.12 shared clipboard: the phone's clipboard (only while the app is open – Android allows nothing else). */
    @PluginMethod
    public void readClipboard(PluginCall call) {
        JSObject r = new JSObject();
        try {
            android.content.ClipboardManager cm = getContext().getSystemService(android.content.ClipboardManager.class);
            android.content.ClipData d = cm == null ? null : cm.getPrimaryClip();
            CharSequence t = d != null && d.getItemCount() > 0 ? d.getItemAt(0).coerceToText(getContext()) : null;
            r.put("text", t == null ? "" : t.toString());
            r.put("fromPc", JarvisLink.prefs(getContext()).getString("clip_from_pc", ""));
        } catch (Exception e) {
            r.put("text", "");
        }
        call.resolve(r);
    }

    /** 3.12 download the new JARVIS.apk and open Android's install dialog (progress as "updateProgress" events). */
    @PluginMethod
    public void installUpdate(PluginCall call) {
        String url = call.getString("url", "");
        if (!ApkUpdate.canInstall(getContext())) {
            call.reject("povol instalaci z JARVISe a ťukni znovu");
            return;
        }
        new Thread(() -> {
            try {
                java.io.File apk = ApkUpdate.download(getContext(), url, p -> {
                    JSObject d = new JSObject();
                    d.put("p", p);
                    notifyListeners("updateProgress", d);
                });
                ApkUpdate.openInstaller(getContext(), apk);
                call.resolve();
            } catch (Exception e) {
                call.reject(e.getMessage() == null ? "aktualizace se nepovedla" : e.getMessage());
            }
        }, "jarvis-apk-update").start();
    }

    @PluginMethod
    public void requestPhone(PluginCall call) {
        requestPermissionForAlias("phone", call, "afterPhone");
    }

    @PermissionCallback
    private void afterPhone(PluginCall call) {
        status(call);
    }

    private void open(Intent i, PluginCall call) {
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            call.resolve();
        } catch (Exception e) {
            call.reject(e.getMessage());
        }
    }

    /** 3.12 the photos permission for "ťuk o monitor" (Android 13+: images only) */
    @PluginMethod
    public void requestPhotos(PluginCall call) {
        String p = Build.VERSION.SDK_INT >= 33 ? Manifest.permission.READ_MEDIA_IMAGES : Manifest.permission.READ_EXTERNAL_STORAGE;
        if (!JarvisLink.has(getContext(), p) && getActivity() != null) getActivity().requestPermissions(new String[] { p }, 4712);
        status(call);
    }

    @PluginMethod
    public void openNotificationAccess(PluginCall call) {
        open(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS), call);
    }

    @PluginMethod
    public void openFullScreen(PluginCall call) {
        if (Build.VERSION.SDK_INT >= 34) {
            open(new Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:" + getContext().getPackageName())), call);
        } else call.resolve();
    }

    @PluginMethod
    public void openOverlay(PluginCall call) {
        open(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getContext().getPackageName())), call);
    }

    @PluginMethod
    public void openBattery(PluginCall call) {
        open(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getContext().getPackageName())), call);
    }

    /** A command that arrived over the WebSocket while the app is open (the background link is off). */
    @PluginMethod
    public void handle(PluginCall call) {
        try {
            JSONObject cmd = new JSONObject(call.getObject("cmd").toString());
            JSObject r = new JSObject();
            r.put("state", JarvisLink.run(getContext(), cmd, true));
            call.resolve(r);
        } catch (Exception e) {
            call.reject(e.getMessage());
        }
    }

    /** OMEGA 136 / 722: what the home-screen widget shows (short texts only, nothing secret). */
    @PluginMethod
    public void widget(PluginCall call) {
        android.content.SharedPreferences.Editor e = JarvisWidget.prefs(getContext()).edit();
        e.putString("status", call.getString("status", ""));
        e.putString("task", call.getString("task", ""));
        e.putString("pins", call.getString("pins", ""));
        e.apply();
        JarvisWidget.refresh(getContext());
        call.resolve();
    }

    @PluginMethod
    public void takePendingReply(PluginCall call) {
        JSObject r = new JSObject();
        r.put("reply", pendingReply != null);
        if (pendingReply != null) r.put("callId", pendingReply.getString("callId"));
        pendingReply = null;
        call.resolve(r);
    }
}
