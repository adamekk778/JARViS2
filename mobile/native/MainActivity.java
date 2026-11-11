package cz.adamekk.jarvis;

import android.content.Intent;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.graphics.drawable.Icon;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;

import java.util.Collections;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    /** 3.12 the app is on screen: the knock-to-PC of the background service steps aside (the app has its own) */
    static volatile boolean visible;

    @Override
    public void onResume() {
        super.onResume();
        visible = true;
    }

    @Override
    public void onPause() {
        visible = false;
        super.onPause();
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(JarvisPhonePlugin.class);
        super.onCreate(savedInstanceState);
        handle(getIntent());
        shareShortcut();
    }

    /** 3.12 a long-lived sharing shortcut: "Na PC" shows up first in the gallery's share sheet (Android 10+). */
    private void shareShortcut() {
        if (Build.VERSION.SDK_INT < 29) return;
        try {
            ShortcutManager sm = getSystemService(ShortcutManager.class);
            if (sm == null) return;
            ShortcutInfo s = new ShortcutInfo.Builder(this, "share_pc")
                .setShortLabel(getString(R.string.sc_share)).setLongLabel(getString(R.string.sc_share_long))
                .setIcon(Icon.createWithResource(this, R.mipmap.ic_launcher))
                .setIntent(new Intent(Intent.ACTION_VIEW, Uri.parse("jarvis://open/photo")).setClass(this, MainActivity.class))
                .setCategories(Collections.singleton("cz.adamekk.jarvis.SHARE_TO_PC"))
                .setLongLived(true).setRank(0).build();
            if (Build.VERSION.SDK_INT >= 30) sm.pushDynamicShortcut(s);
            else sm.addDynamicShortcuts(Collections.singletonList(s));
        } catch (Exception ignored) { }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handle(intent);
    }

    /** "Odpovědět" on JARVIS's call: the app opens ready to talk. */
    private void handle(Intent i) {
        if (i != null && i.getBooleanExtra("jarvis_reply", false)) JarvisPhonePlugin.reply(i.getStringExtra("call_id"));
    }
}
