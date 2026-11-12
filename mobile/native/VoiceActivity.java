package cz.adamekk.jarvis;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.util.Locale;

/**
 * 3.12 Hlas z telefonu se sluchátky: hold the headphones' button (or "Mluvit" in JARVIS's notification) and talk.
 * Always visible – this window with a beep at the start; the microphone runs only while it shows "Poslouchám",
 * never in the background. The recording goes to your own PC (JARVIS there understands it and answers); the
 * answer is played in the headphones. Over the lock screen too, and away from home through JARVIS Link.
 */
public class VoiceActivity extends Activity {
    private static final int RATE = 16000;
    private static final int REQ_MIC = 4720;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean recording;
    private volatile int session;              // a newer start makes an older answer drop silently
    private TextView status, said, answer;
    private View level;
    private Button again;
    private MediaPlayer player;
    private TextToSpeech tts;
    private AudioManager am;
    private AudioFocusRequest focus;
    private boolean viaHeadset;
    private final Runnable autoClose = this::finish;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(true); setTurnScreenOn(true); }
        else getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        setContentView(buildUi());
        begin();
    }

    @Override
    protected void onNewIntent(Intent intent) {        // the button again: done talking / talk again
        super.onNewIntent(intent);
        if (recording) recording = false;
        else begin();
    }

    // ---------- the window: a dark card at the bottom, over whatever was on the screen ----------
    private View buildUi() {
        float d = getResources().getDisplayMetrics().density;
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.argb(150, 0, 0, 0));
        root.setOnClickListener(v -> finish());
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding((int) (22 * d), (int) (20 * d), (int) (22 * d), (int) (18 * d));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.rgb(14, 16, 20));
        bg.setCornerRadius(26 * d);
        bg.setStroke((int) d, Color.argb(40, 255, 255, 255));
        card.setBackground(bg);
        card.setElevation(20 * d);
        card.setClickable(true);
        TextView title = text("JARVIS", 13, Color.argb(150, 255, 255, 255));
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLetterSpacing(0.18f);
        status = text("Připravuji…", 22, Color.WHITE);
        status.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        level = new View(this);
        GradientDrawable lv = new GradientDrawable();
        lv.setColor(Color.rgb(52, 211, 153));
        lv.setCornerRadius(3 * d);
        level.setBackground(lv);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams((int) (8 * d), (int) (5 * d));
        lp.topMargin = (int) (12 * d);
        lp.bottomMargin = (int) (6 * d);
        said = text("", 15, Color.argb(170, 255, 255, 255));
        answer = text("", 17, Color.WHITE);
        answer.setLineSpacing(0, 1.15f);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.END);
        again = button("Mluvit znovu", true);
        again.setOnClickListener(v -> begin());
        Button close = button("Zavřít", false);
        close.setOnClickListener(v -> finish());
        row.addView(close);
        row.addView(again);
        card.addView(title);
        card.addView(status);
        card.addView(level, lp);
        card.addView(said);
        card.addView(answer);
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        rp.topMargin = (int) (16 * d);
        card.addView(row, rp);
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
        cp.setMargins((int) (12 * d), 0, (int) (12 * d), (int) (24 * d));
        root.addView(card, cp);
        return root;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setPadding(0, (int) (4 * getResources().getDisplayMetrics().density), 0, 0);
        return t;
    }

    private Button button(String s, boolean primary) {
        float d = getResources().getDisplayMetrics().density;
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextColor(primary ? Color.rgb(6, 24, 17) : Color.WHITE);
        GradientDrawable g = new GradientDrawable();
        g.setColor(primary ? Color.rgb(52, 211, 153) : Color.argb(30, 255, 255, 255));
        g.setCornerRadius(20 * d);
        b.setBackground(g);
        b.setMinHeight((int) (40 * d));
        b.setPadding((int) (18 * d), 0, (int) (18 * d), 0);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, (int) (40 * d));
        p.setMarginStart((int) (8 * d));
        b.setLayoutParams(p);
        return b;
    }

    private void show(String st, String you, String jarvis) {
        ui.post(() -> {
            if (st != null) status.setText(st);
            if (you != null) said.setText(you);
            if (jarvis != null) answer.setText(jarvis);
        });
    }

    // ---------- listen ----------
    private void begin() {
        ui.removeCallbacks(autoClose);
        stopPlayback();
        if (JarvisLink.base(this).isEmpty()) { show("Nejdřív spáruj telefon s PC", "", "Otevři aplikaci JARVIS a naskenuj kód z PC."); return; }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            show("Povol mikrofon", "", "JARVIS ho používá, jen když je vidět tohle okno.");
            requestPermissions(new String[] { Manifest.permission.RECORD_AUDIO }, REQ_MIC);
            return;
        }
        final int my = ++session;
        again.setEnabled(false);
        show("Poslouchám…", "", "");
        new Thread(() -> listen(my), "jarvis-voice").start();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        if (code == REQ_MIC && res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED) begin();
        else show("Bez mikrofonu to nejde", "", "Povolíš ho v Nastavení Androidu → Aplikace → JARVIS → Oprávnění.");
    }

    private void listen(int my) {
        grabFocus();
        useHeadsetMic();
        beep(ToneGenerator.TONE_PROP_BEEP);
        byte[] pcm = record(my);
        releaseHeadsetMic();
        beep(ToneGenerator.TONE_PROP_ACK);
        if (my != session) return;
        if (pcm == null) { done("Nic jsem neslyšel", "", "Zkus to znovu – mluv hned po pípnutí."); return; }
        show("Přemýšlím…", "", "");
        try {
            String r = JarvisLink.httpBytes(this, "/api/phone/voice", wav(pcm), "audio/wav", 150000);
            if (my != session) return;
            JSONObject o = new JSONObject(r);
            String heard = o.optString("heard", ""), reply = o.optString("reply", "");
            show("", heard.isEmpty() ? "" : "„" + heard + "“", reply);
            String audio = o.optString("audio", "");
            if (!audio.isEmpty()) play(Base64.decode(audio, Base64.DEFAULT), o.optString("mime", "audio/mpeg"), reply, my);
            else speak(reply, my);
        } catch (Exception e) {
            done("Na PC se to nedostalo", "", "Je PC zapnuté a JARVIS na něm běží? (" + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()) + ")");
        }
    }

    /** 16 kHz mono; ends 1.2 s after you stop talking, at 15 s, or when the button is pressed again. null = no speech. */
    private byte[] record(int my) {
        int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec;
        try {
            rec = new AudioRecord(viaHeadset ? MediaRecorder.AudioSource.VOICE_COMMUNICATION : MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min, RATE));
            rec.startRecording();
        } catch (Exception e) {
            return null;
        }
        recording = true;
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        short[] frame = new short[RATE / 50];                       // 20 ms
        double floor = 0;
        int frames = 0, quietMs = 0, heardMs = 0;
        try {
            while (recording && my == session && frames * 20 < 15000) {
                int n = rec.read(frame, 0, frame.length);
                if (n <= 0) continue;
                frames++;
                double sum = 0;
                for (int i = 0; i < n; i++) sum += (double) frame[i] * frame[i];
                double rms = Math.sqrt(sum / n);
                if (frames <= 15) floor = Math.max(floor, rms);       // the first 300 ms: the room's own noise
                boolean voice = frames > 15 && rms > Math.max(floor * 2.5, 500);
                if (voice) { heardMs += 20; quietMs = 0; } else quietMs += 20;
                for (int i = 0; i < n; i++) { out.write(frame[i] & 0xff); out.write((frame[i] >> 8) & 0xff); }
                final float w = (float) Math.min(1.0, rms / 6000.0);
                ui.post(() -> level.setScaleX(1 + w * 30));
                if (heardMs >= 300 && quietMs >= 1200) break;
                if (heardMs < 300 && frames * 20 >= 7000) break;      // nothing said for 7 s
            }
        } finally {
            recording = false;
            try { rec.stop(); } catch (Exception ignored) { }
            rec.release();
            ui.post(() -> level.setScaleX(1));
        }
        return heardMs >= 300 ? out.toByteArray() : null;
    }

    private static byte[] wav(byte[] pcm) {
        ByteArrayOutputStream o = new ByteArrayOutputStream(pcm.length + 44);
        int byteRate = RATE * 2;
        writeStr(o, "RIFF"); writeInt(o, 36 + pcm.length); writeStr(o, "WAVE");
        writeStr(o, "fmt "); writeInt(o, 16); writeShort(o, 1); writeShort(o, 1); writeInt(o, RATE); writeInt(o, byteRate); writeShort(o, 2); writeShort(o, 16);
        writeStr(o, "data"); writeInt(o, pcm.length);
        o.write(pcm, 0, pcm.length);
        return o.toByteArray();
    }

    private static void writeStr(ByteArrayOutputStream o, String s) { for (char ch : s.toCharArray()) o.write(ch); }
    private static void writeInt(ByteArrayOutputStream o, int v) { o.write(v); o.write(v >> 8); o.write(v >> 16); o.write(v >> 24); }
    private static void writeShort(ByteArrayOutputStream o, int v) { o.write(v); o.write(v >> 8); }

    // ---------- the headphones: their microphone while listening, the answer in them ----------
    private void useHeadsetMic() {
        viaHeadset = false;
        if (Build.VERSION.SDK_INT < 31 || am == null) return;     // older Android: the phone's own microphone
        try {
            for (AudioDeviceInfo dev : am.getAvailableCommunicationDevices()) {
                int t = dev.getType();
                if (t == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || t == AudioDeviceInfo.TYPE_BLE_HEADSET) {
                    viaHeadset = am.setCommunicationDevice(dev);
                    if (viaHeadset) Thread.sleep(700);              // the headset needs a moment to switch its microphone on
                    break;
                }
            }
        } catch (Exception ignored) { viaHeadset = false; }
    }

    private void releaseHeadsetMic() {
        if (viaHeadset && Build.VERSION.SDK_INT >= 31 && am != null) {
            try { am.clearCommunicationDevice(); } catch (Exception ignored) { }
        }
        viaHeadset = false;
    }

    private void grabFocus() {                                    // music pauses while you talk and JARVIS answers
        if (am == null || Build.VERSION.SDK_INT < 26) return;
        try {
            focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
                    .setAudioAttributes(attrs()).build();
            am.requestAudioFocus(focus);
        } catch (Exception ignored) { }
    }

    private void dropFocus() {
        if (am != null && focus != null && Build.VERSION.SDK_INT >= 26) {
            try { am.abandonAudioFocusRequest(focus); } catch (Exception ignored) { }
        }
        focus = null;
    }

    private static AudioAttributes attrs() {
        return new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
    }

    private void beep(int tone) {
        try {
            ToneGenerator g = new ToneGenerator(viaHeadset ? AudioManager.STREAM_VOICE_CALL : AudioManager.STREAM_MUSIC, 70);
            g.startTone(tone, 160);
            Thread.sleep(220);
            g.release();
        } catch (Exception ignored) { }
    }

    private void play(byte[] audio, String mime, String text, int my) {
        try {
            File f = new File(getCacheDir(), mime.contains("wav") ? "jarvis-answer.wav" : "jarvis-answer.mp3");
            try (FileOutputStream os = new FileOutputStream(f)) { os.write(audio); }
            ui.post(() -> {
                if (my != session) return;
                try {
                    stopPlayback();
                    player = new MediaPlayer();
                    player.setAudioAttributes(attrs());
                    player.setDataSource(f.getAbsolutePath());
                    player.setOnCompletionListener(mp -> done(null, null, null));
                    player.prepare();
                    player.start();
                    status.setText("JARVIS odpovídá");
                } catch (Exception e) {
                    speak(text, my);
                }
            });
        } catch (Exception e) {
            speak(text, my);
        }
    }

    /** No audio from the PC: the phone's own Czech voice reads the answer. */
    private void speak(final String text, int my) {
        if (text == null || text.isEmpty()) { done("Hotovo", null, null); return; }
        ui.post(() -> {
            if (my != session) return;
            status.setText("JARVIS odpovídá");
            if (tts != null) { say(text); return; }
            tts = new TextToSpeech(getApplicationContext(), st -> {
                if (st == TextToSpeech.SUCCESS) {
                    tts.setLanguage(new Locale("cs", "CZ"));
                    tts.setAudioAttributes(attrs());
                    say(text);
                } else done("Hotovo", null, null);
            });
        });
    }

    private void say(String text) {
        tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
            @Override public void onStart(String id) { }
            @Override public void onDone(String id) { done(null, null, null); }
            @Override public void onError(String id) { done(null, null, null); }
        });
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis-answer");
    }

    private void done(String st, String you, String jarvis) {
        dropFocus();
        show(st != null ? st : "Hotovo – podrž tlačítko a mluv dál", you, jarvis);
        ui.post(() -> {
            again.setEnabled(true);
            ui.removeCallbacks(autoClose);
            ui.postDelayed(autoClose, 12000);
        });
    }

    private void stopPlayback() {
        if (player != null) {
            try { player.stop(); } catch (Exception ignored) { }
            player.release();
            player = null;
        }
        if (tts != null) tts.stop();
    }

    @Override
    protected void onDestroy() {
        session++;
        recording = false;
        ui.removeCallbacksAndMessages(null);
        stopPlayback();
        if (tts != null) { tts.shutdown(); tts = null; }
        releaseHeadsetMic();
        dropFocus();
        super.onDestroy();
    }
}
