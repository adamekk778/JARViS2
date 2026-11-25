package cz.adamekk.jarvis.wear;

import androidx.wear.watchface.complications.data.ComplicationData;
import androidx.wear.watchface.complications.data.ComplicationType;
import androidx.wear.watchface.complications.data.PlainComplicationText;
import androidx.wear.watchface.complications.data.ShortTextComplicationData;
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceService;
import androidx.wear.watchface.complications.datasource.ComplicationRequest;

import org.json.JSONObject;

/**
 * 3.20 (151) JARVIS on your watch face: a complication (SHORT_TEXT) with the next meeting's time, the count of what
 * waits for your approval, or "OK". Add it on any watch face that takes complications – it is not a watch face itself.
 */
public class StatusComplication extends ComplicationDataSourceService {
    private ComplicationData data(String shortText, String title) {
        return new ShortTextComplicationData.Builder(new PlainComplicationText.Builder(shortText).build(),
                new PlainComplicationText.Builder("JARVIS: " + title).build())
                .setTitle(new PlainComplicationText.Builder(title).build()).build();
    }

    @Override
    public void onComplicationRequest(ComplicationRequest request, ComplicationRequestListener listener) {
        if (request.getComplicationType() != ComplicationType.SHORT_TEXT) {
            try { listener.onComplicationData(null); } catch (Exception ignored) { }
            return;
        }
        new Thread(() -> {
            String s = Api.prefs(this).getString("compl_short", "OK"), t = Api.prefs(this).getString("compl_title", "JARVIS");
            if (Api.paired(this)) {
                try {
                    JSONObject r = new JSONObject(Api.get(this, "/api/watch/complication", 8000));
                    s = r.optString("short", s);
                    t = r.optString("title", t);
                    Api.prefs(this).edit().putString("compl_short", s).putString("compl_title", t).apply();
                } catch (Exception ignored) { }
            }
            try { listener.onComplicationData(data(s, t)); } catch (Exception ignored) { }
        }, "jarvis-complication").start();
    }

    @Override
    public ComplicationData getPreviewData(ComplicationType type) {
        return type == ComplicationType.SHORT_TEXT ? data("14:00", "Porada") : null;
    }
}
