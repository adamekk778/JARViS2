package cz.adamekk.jarvis.wear;

import androidx.wear.protolayout.ActionBuilders;
import androidx.wear.protolayout.LayoutElementBuilders;
import androidx.wear.protolayout.ModifiersBuilders;
import androidx.wear.protolayout.ResourceBuilders;
import androidx.wear.protolayout.TimelineBuilders;
import androidx.wear.tiles.RequestBuilders;
import androidx.wear.tiles.TileBuilders;
import androidx.wear.tiles.TileService;

import com.google.common.util.concurrent.Futures;
import com.google.common.util.concurrent.ListenableFuture;

/** 3.18 The JARVIS tile: a short status from the PC (a print, parcels to pick up…) and a tap = ask by voice. */
public class JarvisTile extends TileService {
    private static final String RES = "1";

    @Override
    protected ListenableFuture<TileBuilders.Tile> onTileRequest(RequestBuilders.TileRequest request) {
        String status = Api.prefs(this).getString("status", "");
        if (Api.paired(this)) {
            new Thread(() -> { try { Api.status(this); } catch (Exception ignored) { } }, "jarvis-tile").start();
        } else {
            status = "Otevři JARVIS a spáruj s PC";
        }
        ModifiersBuilders.Clickable open = new ModifiersBuilders.Clickable.Builder()
                .setId("ask")
                .setOnClick(new ActionBuilders.LaunchAction.Builder()
                        .setAndroidActivity(new ActionBuilders.AndroidActivity.Builder()
                                .setPackageName(getPackageName())
                                .setClassName(MainActivity.class.getName())
                                .addKeyToExtraMapping("ask", ActionBuilders.booleanExtra(true))
                                .build())
                        .build())
                .build();
        LayoutElementBuilders.Column column = new LayoutElementBuilders.Column.Builder()
                .addContent(new LayoutElementBuilders.Text.Builder().setText("JARVIS").build())
                .addContent(new LayoutElementBuilders.Text.Builder()
                        .setText(status.isEmpty() ? "Ťukni a zeptej se" : status).setMaxLines(3).build())
                .setModifiers(new ModifiersBuilders.Modifiers.Builder().setClickable(open).build())
                .build();
        LayoutElementBuilders.Box root = new LayoutElementBuilders.Box.Builder().addContent(column).build();
        TileBuilders.Tile tile = new TileBuilders.Tile.Builder()
                .setResourcesVersion(RES)
                .setFreshnessIntervalMillis(10 * 60 * 1000)
                .setTileTimeline(TimelineBuilders.Timeline.fromLayoutElement(root))
                .build();
        return Futures.immediateFuture(tile);
    }

    @Override
    protected ListenableFuture<ResourceBuilders.Resources> onTileResourcesRequest(RequestBuilders.ResourcesRequest request) {
        return Futures.immediateFuture(new ResourceBuilders.Resources.Builder().setVersion(RES).build());
    }
}
