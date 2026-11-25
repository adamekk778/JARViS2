package cz.adamekk.jarvis.wear;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Looper;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * 3.20 (147) běh s tempem: set the pace (5:30 = min/km); every 30 s the watch compares the last minute's pace –
 * one long buzz = speed up, three short = ease off. (160) Konec saves the workout to the PC's diary (time, km, heart
 * rate). Without GPS it records the time and the heart rate only (a gym workout).
 */
public class RunActivity extends Activity implements LocationListener, SensorEventListener {
    private TextView info;
    private EditText target;
    private long start;
    private double km;
    private Location prev;
    private final java.util.ArrayDeque<double[]> window = new java.util.ArrayDeque<>();   // [time ms, km]
    private long lastCheck;
    private int hrSum, hrN, hrMax;
    private String kind = "run";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        kind = getIntent().getStringExtra("kind") == null ? "run" : getIntent().getStringExtra("kind");
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER_HORIZONTAL);
        l.setBackgroundColor(Color.BLACK);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        l.setPadding(pad, pad, pad, pad);
        target = new EditText(this);
        target.setHint("Tempo 5:30");
        target.setText(Api.prefs(this).getString("pace", ""));
        info = new TextView(this);
        info.setTextColor(Color.WHITE);
        info.setGravity(Gravity.CENTER);
        Button go = new Button(this);
        go.setText("Start");
        go.setOnClickListener(v -> {
            if (start == 0) { begin(); go.setText("Konec"); } else { finishWorkout(); go.setEnabled(false); }
        });
        if ("run".equals(kind)) l.addView(target);
        l.addView(go);
        l.addView(info);
        setContentView(l);
    }

    private double targetSec() {
        String t = target.getText().toString().trim();
        Api.prefs(this).edit().putString("pace", t).apply();
        try {
            if (t.contains(":")) {
                String[] p = t.split(":");
                return Integer.parseInt(p[0].trim()) * 60 + Integer.parseInt(p[1].trim());
            }
            return t.isEmpty() ? 0 : Double.parseDouble(t.replace(',', '.')) * 60;
        } catch (Exception e) {
            return 0;
        }
    }

    @SuppressWarnings("MissingPermission")
    private void begin() {
        start = System.currentTimeMillis();
        if ("run".equals(kind) && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            LocationManager lm = getSystemService(LocationManager.class);
            if (lm != null) lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 2000, 5, this, Looper.getMainLooper());
        } else if ("run".equals(kind)) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 1);
        }
        SensorManager sm = getSystemService(SensorManager.class);
        Sensor h = sm == null ? null : sm.getDefaultSensor(Sensor.TYPE_HEART_RATE);
        if (h != null && checkSelfPermission(Manifest.permission.BODY_SENSORS) == PackageManager.PERMISSION_GRANTED) {
            sm.registerListener(this, h, SensorManager.SENSOR_DELAY_NORMAL);
        }
        info.setText("Běží…");
    }

    @Override
    public void onLocationChanged(Location loc) {
        if (start == 0) return;
        if (prev != null) km += prev.distanceTo(loc) / 1000.0;
        prev = loc;
        long now = System.currentTimeMillis();
        window.addLast(new double[]{now, km});
        while (!window.isEmpty() && now - window.peekFirst()[0] > 60_000) window.removeFirst();
        double[] first = window.peekFirst();
        double dk = first == null ? 0 : km - first[1];
        double sec = first == null ? 0 : (now - first[0]) / 1000.0;
        double pace = dk > 0.02 ? sec / dk : 0;
        info.setText(String.format(java.util.Locale.ROOT, "%.2f km · %s/km", km, pace > 0 ? ((int) pace / 60) + ":" + String.format(java.util.Locale.ROOT, "%02d", (int) pace % 60) : "–"));
        if (now - lastCheck > 30_000 && sec > 40) {
            lastCheck = now;
            String fb = Buzz.pace(targetSec(), pace);
            if ("slow".equals(fb)) Buzz.play(this, Buzz.SLOW, false);
            else if ("fast".equals(fb)) Buzz.play(this, Buzz.FAST, false);
        }
    }

    @Override
    public void onSensorChanged(SensorEvent e) {
        int bpm = Math.round(e.values[0]);
        if (bpm < 30 || bpm > 230) return;
        hrSum += bpm;
        hrN++;
        hrMax = Math.max(hrMax, bpm);
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    private void finishWorkout() {
        stopSensors();
        final double minutes = (System.currentTimeMillis() - start) / 60000.0;
        final double dist = km;
        final int avg = hrN > 0 ? hrSum / hrN : 0, max = hrMax;
        info.setText("Ukládám…");
        new Thread(() -> {
            String m;
            try {
                JSONObject b = new JSONObject().put("kind", kind).put("minutes", minutes).put("km", dist).put("hr_avg", avg).put("hr_max", max);
                m = Api.post(this, "/api/watch/workout", b, 10000).optString("text", "Uloženo.");
            } catch (Exception e) {
                m = "Neuloženo: " + e.getMessage();
            }
            final String shown = m;
            runOnUiThread(() -> info.setText(shown));
        }).start();
    }

    private void stopSensors() {
        LocationManager lm = getSystemService(LocationManager.class);
        if (lm != null) lm.removeUpdates(this);
        SensorManager sm = getSystemService(SensorManager.class);
        if (sm != null) sm.unregisterListener(this);
    }

    @Override
    protected void onDestroy() {
        stopSensors();
        super.onDestroy();
    }
}
