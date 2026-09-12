package com.skymusic.player

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build

class SkyMusicApp : Application() {

    companion object {
        const val CHANNEL_ID = "skymusic_foreground_channel"
        lateinit var instance: SkyMusicApp
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        try {
            createNotificationChannel()
        } catch (e: Throwable) {
            e.printStackTrace()
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "SkyMusic 弹琴悬浮服务",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "保持光遇自动弹琴悬浮窗稳定运行"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }
}
