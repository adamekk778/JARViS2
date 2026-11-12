package cz.adamekk.jarvis;

import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/**
 * 3.12 the JARVIS tile in the quick settings (pull the bar down, next to Wi-Fi and the torch): one tap opens the
 * visible voice window – talk to JARVIS without the headphones, also with the phone locked. Nothing listens until
 * you tap it.
 */
public class JarvisTile extends TileService {
    @Override
    public void onStartListening() {
        Tile t = getQsTile();
        if (t == null) return;
        t.setState(JarvisLink.base(this).isEmpty() ? Tile.STATE_UNAVAILABLE : Tile.STATE_INACTIVE);
        t.setLabel("JARVIS");
        if (Build.VERSION.SDK_INT >= 29) t.setSubtitle(JarvisLink.base(this).isEmpty() ? "nespárováno" : "mluvit");
        t.updateTile();
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onClick() {
        Intent i = new Intent(this, VoiceActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 2, i, JarvisLink.piFlags()));
        } else {
            startActivityAndCollapse(i);
        }
    }
}
