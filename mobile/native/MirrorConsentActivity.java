package cz.adamekk.jarvis;

import android.app.Activity;
import android.content.Intent;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;

/** 3.12 Telefon na monitoru PC: Android's own "share your screen?" question – nothing is shared without a yes. */
public class MirrorConsentActivity extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        MediaProjectionManager mpm = getSystemService(MediaProjectionManager.class);
        if (mpm == null || MirrorService.running) { finish(); return; }
        startActivityForResult(mpm.createScreenCaptureIntent(), 1);
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result == RESULT_OK && data != null) {
            Intent i = new Intent(this, MirrorService.class).putExtra("code", result).putExtra("data", data);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
            else startService(i);
        }
        finish();
    }
}
