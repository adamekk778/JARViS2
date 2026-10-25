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
        call.resolve(r);
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

    @PluginMethod
    public void takePendingReply(PluginCall call) {
        JSObject r = new JSObject();
        r.put("reply", pendingReply != null);
        if (pendingReply != null) r.put("callId", pendingReply.getString("callId"));
        pendingReply = null;
        call.resolve(r);
    }
}
