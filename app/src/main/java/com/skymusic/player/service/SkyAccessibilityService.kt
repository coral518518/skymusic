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
                val enabledList = am?.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
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
        try {
            val info = serviceInfo ?: AccessibilityServiceInfo()
            info.apply {
                eventTypes = AccessibilityEvent.TYPE_ALL_MASK
                feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
                flags = flags or AccessibilityServiceInfo.FLAG_DEFAULT or
                        AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
                notificationTimeout = 50
            }
            serviceInfo = info
        } catch (e: Throwable) {
            Log.e(TAG, "配置 serviceInfo 异常", e)
        }
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
     * 并发点击一个或多个光遇按键（支持和弦）
     * 采用 dispatchGesture 原生手势模拟，免 Root 免激活
     */
    fun clickKeys(keys: List<Int>, layoutManager: KeyLayoutManager) {
        if (keys.isEmpty()) return

        try {
            val gestureBuilder = GestureDescription.Builder()
            var validStrokes = 0

            // 限制单次手势最多 10 个同时触控点（Android 系统上限）
            for (keyIndex in keys.take(10)) {
                val point = layoutManager.getKeyPosition(keyIndex)
                if (point.x > 0 && point.y > 0) {
                    val path = Path().apply {
                        moveTo(point.x, point.y)
                    }
                    // 触控持续 35ms，既能确保游戏底层触控采样率识别，又极其迅速不粘滞
                    val stroke = GestureDescription.StrokeDescription(path, 0L, 35L)
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
