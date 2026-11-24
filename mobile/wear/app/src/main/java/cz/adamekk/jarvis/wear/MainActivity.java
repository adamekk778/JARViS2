package cz.adamekk.jarvis.wear;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognizerIntent;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 3.18 JARVIS on the watch: pair once (the PC's address + the 6-digit code), then "Zeptat se" by voice. */
public class MainActivity extends Activity {
    private static final int SPEAK = 1;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView answer;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (Api.paired(this)) showAsk(); else showPair();
    }

    private LinearLayout column() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER_HORIZONTAL);
        int pad = (int) (18 * getResources().getDisplayMetrics().density);
        l.setPadding(pad, pad, pad, pad);
        l.setBackgroundColor(Color.BLACK);
        return l;
    }

    private TextView text(String s, float size) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(size);
        t.setTextColor(Color.WHITE);
        t.setGravity(Gravity.CENTER);
        return t;
    }

    private void showPair() {
        LinearLayout l = column();
        l.addView(text("Spáruj s PC: Nastavení → Telefon → Spárovat hodinky", 13));
        final EditText host = new EditText(this);
        host.setHint("Adresa PC (192.168.…)");
        host.setText(Api.prefs(this).getString("host", ""));
        host.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        final EditText code = new EditText(this);
        code.setHint("Kód (6 číslic)");
        code.setInputType(InputType.TYPE_CLASS_NUMBER);
        final TextView msg = text("", 12);
        Button go = new Button(this);
        go.setText("Spárovat");
        go.setOnClickListener(v -> {
            final String h = host.getText().toString(), k = code.getText().toString();
            Api.prefs(this).edit().putString("host", h).apply();
            msg.setText("Párování…");
            io.execute(() -> {
                try {
                    Api.pair(this, h, k);
                    ui.post(this::showAsk);
                } catch (Exception e) {
                    ui.post(() -> msg.setText(String.valueOf(e.getMessage())));
                }
            });
        });
        l.addView(host);
        l.addView(code);
        l.addView(go);
        l.addView(msg);
        ScrollView sv = new ScrollView(this);
        sv.addView(l);
        setContentView(sv);
    }

    private void showAsk() {
        LinearLayout l = column();
        Button ask = new Button(this);
        ask.setText("Zeptat se");
        ask.setOnClickListener(v -> listen());
        answer = text(Api.prefs(this).getString("status", "Ťukni a zeptej se JARVISe."), 14);
        Button unpair = new Button(this);
        unpair.setText("Odpárovat");
        unpair.setOnClickListener(v -> { Api.prefs(this).edit().remove("token").remove("base").apply(); showPair(); });
        l.addView(ask);
        l.addView(answer);
        l.addView(unpair);
        ScrollView sv = new ScrollView(this);
        sv.addView(l);
        setContentView(sv);
        if (getIntent() != null && getIntent().getBooleanExtra("ask", false)) listen();
    }

    private void listen() {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "cs-CZ");
        i.putExtra(RecognizerIntent.EXTRA_PROMPT, "Zeptej se JARVISe");
        try {
            startActivityForResult(i, SPEAK);
        } catch (Exception e) {
            answer.setText("Hodinky nemají rozpoznávání řeči.");
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != SPEAK || result != RESULT_OK || data == null) return;
        ArrayList<String> said = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
        if (said == null || said.isEmpty()) return;
        final String q = said.get(0);
        answer.setText("„" + q + "“…");
        io.execute(() -> {
            String a;
            try { a = Api.ask(this, q); } catch (Exception e) { a = "PC neodpovídá: " + e.getMessage(); }
            final String shown = a;
            ui.post(() -> answer.setText(shown));
        });
    }

    @Override
    protected void onDestroy() {
        io.shutdown();
        super.onDestroy();
    }

    @SuppressWarnings("unused")
    private static void hide(View v) { v.setVisibility(View.GONE); }
}
