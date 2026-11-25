package cz.adamekk.jarvis;

import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** 3.20 (122) a quick-settings tile: mute / unmute the PC with one tap from the phone (the lock screen too). */
public class MuteTile extends TileService {
    @Override
    public void onStartListening() {
        Tile t = getQsTile();
        if (t == null) return;
        boolean muted = JarvisLink.prefs(this).getBoolean("pc_muted", false);
        t.setState(JarvisLink.base(this).isEmpty() ? Tile.STATE_UNAVAILABLE : (muted ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE));
        t.setLabel("Ztlumit PC");
        if (Build.VERSION.SDK_INT >= 29) t.setSubtitle(muted ? "ztlumeno" : "zvuk zapnutý");
        t.updateTile();
    }

    @Override
    public void onClick() {
        boolean muted = !JarvisLink.prefs(this).getBoolean("pc_muted", false);
        JarvisLink.prefs(this).edit().putBoolean("pc_muted", muted).apply();
        PhoneX.pcAction(getApplicationContext(), muted ? "mute" : "unmute", null);
        onStartListening();
    }
}
