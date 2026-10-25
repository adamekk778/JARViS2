package cz.adamekk.jarvis;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** After a restart the link comes back only if you switched it on in the app (it shows its notification). */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction()) && JarvisLink.enabled(c) && !JarvisLink.base(c).isEmpty()) {
            try { LinkService.start(c); } catch (Exception ignored) { }
        }
    }
}
