package com.skymusic.player.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.graphics.Path
import android.provider.Settings
import android.text.TextUtils
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager
import com.skymusic.player.engine.KeyLayoutManager

class SkyAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "SkyAccessibility"

        @Volatile
        var instance: SkyAccessibilityService? = null
            private set

        val isRunning: Boolean
            get() = instance != null

        /**
         * 检查系统无障碍服务是否已对本应用开启
         */
        fun isServiceEnabled(context: Context): Boolean {
            if (instance != null) return true

            try {
                val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager
                // -1 匹配所有无障碍反馈类型
                val enabledList = am?.getEnabledAccessibilityServiceList(-1)
                if (enabledList != null) {
                    for (info in enabledList) {
                        if (info.resolveInfo?.serviceInfo?.packageName == context.packageName) {
                            return true
                        }
                    }
                }
            } catch (e: Throwable) {
                e.printStackTrace()
            }

            try {
                val enabledServicesSetting = Settings.Secure.getString(
                    context.contentResolver,
                    Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
                ) ?: return false

                val colonSplitter = TextUtils.SimpleStringSplitter(':')
                colonSplitter.setString(enabledServicesSetting)

                while (colonSplitter.hasNext()) {
                    val componentName = colonSplitter.next()
                    if (componentName.contains(context.packageName, ignoreCase = true) &&
                        componentName.contains("SkyAccessibilityService", ignoreCase = true)) {
                        return true
                    }
                }
            } catch (e: Throwable) {
                e.printStackTrace()
            }

            return false
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "光遇无障碍自动弹琴服务已连接绑定")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 纯模拟手势触控，无需额外拦截或读取界面内容事件
    }

    override fun onInterrupt() {
        Log.w(TAG, "无障碍服务被中断")
    }

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        Log.i(TAG, "无障碍服务已销毁")
    }

    /**
     * 并发模拟点击光遇按键（支持和弦）
     * 具备防检测随机微偏移算法：在按键内圈中随机散布，打破固定坐标特征
     */
    fun clickKeys(keys: List<Int>, layoutManager: KeyLayoutManager) {
        if (keys.isEmpty()) return

        try {
            val gestureBuilder = GestureDescription.Builder()
            var validStrokes = 0

            val density = resources.displayMetrics.density
            val keyRadius = layoutManager.config.keyRadiusDp * density * layoutManager.config.scale
            // 防检测随机散布半径：对应校准页面内的青蓝虚线内圈 (45%半径范围)
            val jitterRadius = keyRadius * 0.45f

            // 限制单次手势最多 10 个同时触控点（Android 系统上限）
            for ((index, keyIndex) in keys.take(10).withIndex()) {
                val point = layoutManager.getKeyPosition(keyIndex)
                if (point.x > 0 && point.y > 0) {
                    // 极坐标均匀随机分布，模拟真人手指自然点击散布
                    val angle = Math.random() * 2.0 * Math.PI
                    val distance = Math.sqrt(Math.random()) * jitterRadius
                    val targetX = (point.x + distance * Math.cos(angle)).toFloat()
                    val targetY = (point.y + distance * Math.sin(angle)).toFloat()

                    val path = Path().apply {
                        moveTo(targetX, targetY)
                        lineTo(targetX + 1f, targetY + 1f)
                    }

                    // 触控持续时长微调为极短打击 (16ms~20ms)，确保密集音符与快速琶音绝不发生手势冲突或被系统丢弃
                    val duration = (16L..20L).random()

                    // 和弦多键微落差 (0~2ms)，逼真还原多指触屏
                    val startLag = if (index == 0) 0L else (0L..2L).random()

                    val stroke = GestureDescription.StrokeDescription(path, startLag, duration)
                    gestureBuilder.addStroke(stroke)
                    validStrokes++
                }
            }

            if (validStrokes > 0) {
                dispatchGesture(gestureBuilder.build(), null, null)
            }
        } catch (e: Exception) {
            Log.e(TAG, "dispatchGesture 点击执行异常: ${e.message}")
        }
    }
}
