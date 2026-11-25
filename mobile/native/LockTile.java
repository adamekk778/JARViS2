package cz.adamekk.jarvis;

import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** 3.20 (122) a quick-settings tile: lock the PC when you walk away from it. */
public class LockTile extends TileService {
    @Override
    public void onStartListening() {
        Tile t = getQsTile();
        if (t == null) return;
        t.setState(JarvisLink.base(this).isEmpty() ? Tile.STATE_UNAVAILABLE : Tile.STATE_INACTIVE);
        t.setLabel("Zamknout PC");
        if (Build.VERSION.SDK_INT >= 29) t.setSubtitle("JARVIS");
        t.updateTile();
    }

    @Override
    public void onClick() {
        PhoneX.pcAction(getApplicationContext(), "lock", null);
        android.widget.Toast.makeText(this, "Zamykám PC", android.widget.Toast.LENGTH_SHORT).show();
    }
}
