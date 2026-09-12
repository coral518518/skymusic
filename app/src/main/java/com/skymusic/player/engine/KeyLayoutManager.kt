package com.skymusic.player.engine

import android.content.Context
import android.content.SharedPreferences
import android.graphics.PointF
import android.util.DisplayMetrics
import android.view.WindowManager
import com.google.gson.Gson
import com.skymusic.player.model.KeyLayoutConfig

class KeyLayoutManager private constructor(private val context: Context) {

    companion object {
        private const val PREF_NAME = "skymusic_key_layout_pref"
        private const val KEY_CONFIG = "saved_layout_config"

        @Volatile
        private var INSTANCE: KeyLayoutManager? = null

        fun getInstance(context: Context): KeyLayoutManager {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: KeyLayoutManager(context.applicationContext).also { INSTANCE = it }
            }
        }
    }

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
    private val gson = Gson()

    var config: KeyLayoutConfig = loadConfig()
        private set

    init {
        detectAndInitScreen()
    }

    /**
     * 检测屏幕真实尺寸（统一转换为横屏高宽）
     */
    fun detectAndInitScreen() {
        try {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as? WindowManager
            var landscapeW = 2400
            var landscapeH = 1080

            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R && wm != null) {
                val bounds = wm.currentWindowMetrics.bounds
                landscapeW = maxOf(bounds.width(), bounds.height())
                landscapeH = minOf(bounds.width(), bounds.height())
            } else if (wm != null) {
                val metrics = DisplayMetrics()
                @Suppress("DEPRECATION")
                wm.defaultDisplay.getRealMetrics(metrics)
                landscapeW = maxOf(metrics.widthPixels, metrics.heightPixels)
                landscapeH = minOf(metrics.widthPixels, metrics.heightPixels)
            } else {
                val dm = context.resources.displayMetrics
                landscapeW = maxOf(dm.widthPixels, dm.heightPixels)
                landscapeH = minOf(dm.widthPixels, dm.heightPixels)
            }

            if (landscapeW > 0 && landscapeH > 0) {
                if (config.screenWidth != landscapeW || config.screenHeight != landscapeH) {
                    config.autoFit(landscapeW, landscapeH)
                    saveConfig()
                }
            }
        } catch (e: Throwable) {
            e.printStackTrace()
        }
    }

    fun getKeyPosition(keyIndex: Int): PointF {
        return config.getKeyPosition(keyIndex)
    }

    fun getAllKeyPositions(): List<PointF> {
        return (0..14).map { config.getKeyPosition(it) }
    }

    fun moveOffset(deltaXPercent: Float, deltaYPercent: Float) {
        config.centerXPercent = (config.centerXPercent + deltaXPercent).coerceIn(0.2f, 0.8f)
        config.centerYPercent = (config.centerYPercent + deltaYPercent).coerceIn(0.2f, 0.8f)
    }

    fun adjustSpacing(deltaSpacingX: Float, deltaSpacingY: Float) {
        config.spacingXPercent = (config.spacingXPercent + deltaSpacingX).coerceIn(0.04f, 0.15f)
        config.spacingYPercent = (config.spacingYPercent + deltaSpacingY).coerceIn(0.08f, 0.25f)
    }

    fun adjustScale(deltaScale: Float) {
        config.scale = (config.scale + deltaScale).coerceIn(0.6f, 1.6f)
    }

    fun autoFitCurrentScreen() {
        detectAndInitScreen()
        config.autoFit(config.screenWidth, config.screenHeight)
        saveConfig()
    }

    fun resetToDefault() {
        config.autoFit(config.screenWidth, config.screenHeight)
        saveConfig()
    }

    fun saveConfig() {
        val json = gson.toJson(config)
        prefs.edit().putString(KEY_CONFIG, json).apply()
    }

    private fun loadConfig(): KeyLayoutConfig {
        val json = prefs.getString(KEY_CONFIG, null)
        return if (!json.isNullOrEmpty()) {
            try {
                gson.fromJson(json, KeyLayoutConfig::class.java)
            } catch (e: Exception) {
                KeyLayoutConfig()
            }
        } else {
            KeyLayoutConfig()
        }
    }
}
