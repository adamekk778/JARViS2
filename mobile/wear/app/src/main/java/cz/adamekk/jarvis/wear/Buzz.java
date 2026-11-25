package cz.adamekk.jarvis.wear;

import android.content.Context;
import android.os.VibrationEffect;
import android.os.Vibrator;

import org.json.JSONArray;

/** 3.20 (141) the vibration codes: the PC sends the pattern (wait, buzz, wait, buzz… in ms), the wrist plays it. */
final class Buzz {
    private Buzz() { }

    static final long[] SLOW = {0, 300};             // (147) běh: přidej
    static final long[] FAST = {0, 90, 90, 90};      // zvolni
    static final long[] LEFT = {0, 150, 150, 150};   // (149) doleva dvakrát
    static final long[] RIGHT = {0, 150, 150, 150, 150, 150};   // doprava třikrát
    static final long[] ARRIVE = {0, 700};

    static long[] pattern(JSONArray a) {
        if (a == null || a.length() == 0) return new long[]{0, 80};
        int n = Math.min(a.length(), 24);
        long[] out = new long[n];
        for (int k = 0; k < n; k++) out[k] = Math.max(0, Math.min(2000, a.optLong(k)));
        return out;
    }

    @SuppressWarnings("deprecation")
    static void play(Context c, long[] timings, boolean repeat) {
        Vibrator v = c.getSystemService(Vibrator.class);
        if (v == null || !v.hasVibrator()) return;
        v.vibrate(VibrationEffect.createWaveform(timings, repeat ? 0 : -1));
    }

    static void stop(Context c) {
        Vibrator v = c.getSystemService(Vibrator.class);
        if (v != null) v.cancel();
    }

    /** The same rule as phonex.pace_feedback on the PC: 5 % slower than the target = "slow", 5 % faster = "fast". */
    static String pace(double targetSecKm, double currentSecKm) {
        if (targetSecKm <= 0 || currentSecKm <= 0) return "ok";
        if (currentSecKm > targetSecKm * 1.05) return "slow";
        if (currentSecKm < targetSecKm * 0.95) return "fast";
        return "ok";
    }
}
