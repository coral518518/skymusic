package com.skymusic.player.engine

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.DataOutputStream
import java.io.InputStreamReader

object RootTouchController {

    private const val TAG = "RootTouchController"
    private const val PREF_ROOT_MODE = "pref_root_mode_enabled"

    private var rootProcess: Process? = null
    private var outputStream: DataOutputStream? = null

    @Volatile
    var isRootGranted: Boolean = false
        private set

    fun isRootModeEnabled(context: Context): Boolean {
        val sp = context.getSharedPreferences("skymusic_settings", Context.MODE_PRIVATE)
        return sp.getBoolean(PREF_ROOT_MODE, false)
    }

    fun setRootModeEnabled(context: Context, enabled: Boolean) {
        val sp = context.getSharedPreferences("skymusic_settings", Context.MODE_PRIVATE)
        sp.edit().putBoolean(PREF_ROOT_MODE, enabled).apply()
        if (enabled) {
            initSession()
        } else {
            closeSession()
        }
    }

    /**
     * 异步请求 Root 权限并测试 (兼容 KernelSU / APatch / Magisk 安卓 15)
     */
    suspend fun requestRootPermission(): Boolean = withContext(Dispatchers.IO) {
        try {
            val process = Runtime.getRuntime().exec("su")
            val os = DataOutputStream(process.outputStream)
            val reader = BufferedReader(InputStreamReader(process.inputStream))

            os.writeBytes("id\nexit\n")
            os.flush()

            val output = reader.readLine() ?: ""
            process.waitFor()

            isRootGranted = output.contains("uid=0")
            if (isRootGranted) {
                initSession()
            }
            isRootGranted
        } catch (e: Throwable) {
            Log.e(TAG, "Request root failed: ${e.message}")
            isRootGranted = false
            false
        }
    }

    /**
     * 初始化常驻后台 Root Shell 会话，确保毫秒级点击响应与零延迟
     */
    @Synchronized
    private fun initSession(): Boolean {
        if (rootProcess != null && outputStream != null) {
            return true
        }

        return try {
            val p = Runtime.getRuntime().exec("su")
            rootProcess = p
            outputStream = DataOutputStream(p.outputStream)
            isRootGranted = true
            Log.i(TAG, "Root常驻会话已成功建立")
            true
        } catch (e: Throwable) {
            Log.e(TAG, "initSession error: ${e.message}")
            closeSession()
            false
        }
    }

    /**
     * 并发调度真实底层输入系统模拟点击 (Root 模式)
     * 完全绕过无障碍层，防游戏行为检测
     */
    @Synchronized
    fun clickKeys(keys: List<Int>, layoutManager: KeyLayoutManager) {
        if (keys.isEmpty()) return
        if (!initSession()) return

        try {
            val density = layoutManager.config.screenWidth.toFloat() / 2400f
            val keyRadius = layoutManager.config.keyRadiusDp * 2.5f * layoutManager.config.scale
            val jitterRadius = keyRadius * 0.45f

            val sb = StringBuilder()

            for (keyIndex in keys.take(10)) {
                val point = layoutManager.getKeyPosition(keyIndex)
                if (point.x > 0 && point.y > 0) {
                    // 极坐标均匀随机散布
                    val angle = Math.random() * 2.0 * Math.PI
                    val distance = Math.sqrt(Math.random()) * jitterRadius
                    val targetX = (point.x + distance * Math.cos(angle)).toInt()
                    val targetY = (point.y + distance * Math.sin(angle)).toInt()

                    // input tap 并发分发
                    sb.append("input tap $targetX $targetY &\n")
                }
            }

            outputStream?.writeBytes(sb.toString())
            outputStream?.flush()
        } catch (e: Throwable) {
            Log.e(TAG, "clickKeys root execution error: ${e.message}")
            closeSession()
        }
    }

    @Synchronized
    fun closeSession() {
        try {
            outputStream?.writeBytes("exit\n")
            outputStream?.flush()
            outputStream?.close()
        } catch (_: Throwable) {}

        try {
            rootProcess?.destroy()
        } catch (_: Throwable) {}

        rootProcess = null
        outputStream = null
    }
}
