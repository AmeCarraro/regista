package app.regista

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews

/**
 * The music on the home screen: the song playing, play and pause, the next one. With nothing to
 * play, a touch opens the app on «Musica», where a song is chosen. It is drawn again by the player
 * each time something changes (Player.update), and needs nothing else to run.
 */
class MusicWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = show(context)

    companion object {
        /** Draws every music widget on the home screen as the player is now. */
        fun show(context: Context) {
            val manager = AppWidgetManager.getInstance(context) ?: return
            val ids = manager.getAppWidgetIds(ComponentName(context, MusicWidget::class.java))
            if (ids.isEmpty()) return
            val song = Player.queue.getOrNull(Player.index)
            val views = RemoteViews(context.packageName, R.layout.music_widget)
            views.setTextViewText(R.id.widget_title, song?.title ?: "Musica")
            views.setTextViewText(
                R.id.widget_said,
                when {
                    song == null -> context.getString(R.string.widget_choose)
                    Player.problem.isNotEmpty() -> Player.problem
                    Player.loading -> "Un attimo…"
                    !Player.playing -> "In pausa"
                    else -> song.artist.ifBlank { "Regista" }
                },
            )
            views.setImageViewResource(R.id.widget_play, if (Player.playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play)
            val open = PendingIntent.getActivity(
                context,
                1,
                Intent(context, MainActivity::class.java).putExtra(MainActivity.TAB, MainActivity.MUSIC).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            views.setOnClickPendingIntent(R.id.widget, open)
            views.setOnClickPendingIntent(R.id.widget_play, if (song == null) open else Player.pressed(context, if (Player.playing) Player.PAUSE else Player.RESUME))
            views.setOnClickPendingIntent(R.id.widget_next, if (song == null) open else Player.pressed(context, Player.NEXT))
            manager.updateAppWidget(ids, views)
        }
    }
}
