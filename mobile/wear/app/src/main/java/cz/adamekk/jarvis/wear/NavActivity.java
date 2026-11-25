package cz.adamekk.jarvis.wear;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Looper;
import android.speech.RecognizerIntent;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;

/**
 * 3.20 (149) navigace vibracemi: say where, the PC plans a walking route (OpenStreetMap), the watch buzzes ~25 m before
 * each turn – two = left, three = right, one long = you are there. Look at the display only when you want to.
 */
public class NavActivity extends Activity implements LocationListener {
    private static final int SPEAK = 2;
    private TextView info;
    private JSONArray steps = new JSONArray();
    private int next = 1;
    private Location here;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER);
        l.setBackgroundColor(Color.BLACK);
        info = new TextView(this);
        info.setTextColor(Color.WHITE);
        info.setGravity(Gravity.CENTER);
        info.setText("Kam to bude?");
        Button say = new Button(this);
        say.setText("Říct cíl");
        say.setOnClickListener(v -> listen());
        l.addView(info);
        l.addView(say);
        setContentView(l);
        startGps();
    }

    @SuppressWarnings("MissingPermission")
    private void startGps() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 1);
            return;
        }
        LocationManager lm = getSystemService(LocationManager.class);
        if (lm != null) lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 2000, 3, this, Looper.getMainLooper());
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        if (res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED) startGps();
    }

    private void listen() {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "cs-CZ");
        try { startActivityForResult(i, SPEAK); } catch (Exception e) { info.setText("Hodinky nemají rozpoznávání řeči."); }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != SPEAK || result != RESULT_OK || data == null) return;
        ArrayList<String> said = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
        if (said == null || said.isEmpty()) return;
        if (here == null) { info.setText("Čekám na GPS…"); return; }
        final String to = said.get(0);
        final double lat = here.getLatitude(), lon = here.getLongitude();
        info.setText("Plánuji trasu na " + to + "…");
        new Thread(() -> {
            String m;
            try {
                JSONObject r = Api.post(this, "/api/watch/route", new JSONObject().put("lat", lat).put("lon", lon).put("to", to), 30000);
                if (r.optBoolean("ok")) {
                    steps = r.optJSONArray("steps") == null ? new JSONArray() : r.optJSONArray("steps");
                    next = 1;
                    m = r.optDouble("km") + " km, asi " + r.optInt("minutes") + " min";
                } else {
                    m = r.optString("message", "Trasa nenalezena.");
                }
            } catch (Exception e) {
                m = "PC neodpovídá.";
            }
            final String shown = m;
            runOnUiThread(() -> info.setText(shown));
        }).start();
    }

    @Override
    public void onLocationChanged(Location loc) {
        here = loc;
        if (next >= steps.length()) return;
        JSONObject s = steps.optJSONObject(next);
        if (s == null) return;
        float[] d = new float[1];
        Location.distanceBetween(loc.getLatitude(), loc.getLongitude(), s.optDouble("lat"), s.optDouble("lon"), d);
        String turn = s.optString("turn");
        info.setText(("left".equals(turn) ? "← " : "right".equals(turn) ? "→ " : "● ") + Math.round(d[0]) + " m " + s.optString("street"));
        if (d[0] < 25) {
            Buzz.play(this, "left".equals(turn) ? Buzz.LEFT : "right".equals(turn) ? Buzz.RIGHT : Buzz.ARRIVE, false);
            next++;
            if ("arrive".equals(turn)) info.setText("Jsi v cíli.");
        }
    }

    @Override
    protected void onDestroy() {
        LocationManager lm = getSystemService(LocationManager.class);
        if (lm != null) lm.removeUpdates(this);
        super.onDestroy();
    }
}
