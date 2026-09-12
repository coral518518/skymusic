package com.skymusic.player.model

import android.graphics.PointF

/**
 * 光遇 15 键屏幕布局配置
 * 横屏模式下的 3 行 x 5 列
 */
data class KeyLayoutConfig(
    var screenWidth: Int = 2400,
    var screenHeight: Int = 1080,
    var centerXPercent: Float = 0.475f,   // 键盘中心 X 比例 (往左微调5下：0.50f -> 0.475f)
    var centerYPercent: Float = 0.440f,   // 键盘中心 Y 比例 (往上微调20下：0.54f -> 0.440f)
    var spacingXPercent: Float = 0.082f, // 列间距比例 (约 8.2% 屏幕宽)
    var spacingYPercent: Float = 0.150f, // 行间距比例 (约 15% 屏幕高)
    var scale: Float = 1.09f,            // 整体缩放系数 (放大3下：1.00f -> 1.09f)
    var keyRadiusDp: Float = 26f         // 光圈视觉半径 dp
) {
    /**
     * 计算指定按键索引 (0 ~ 14) 的屏幕像素坐标
     *
     * 0  1  2  3  4  (Row 0: 0..4)
     * 5  6  7  8  9  (Row 1: 5..9)
     * 10 11 12 13 14 (Row 2: 10..14)
     */
    fun getKeyPosition(keyIndex: Int): PointF {
        if (keyIndex < 0 || keyIndex > 14) {
            return PointF(0f, 0f)
        }
        val row = keyIndex / 5       // 0, 1, 2
        val col = keyIndex % 5       // 0, 1, 2, 3, 4

        val centerX = screenWidth * centerXPercent
        val centerY = screenHeight * centerYPercent

        val deltaX = (screenWidth * spacingXPercent) * scale
        val deltaY = (screenHeight * spacingYPercent) * scale

        // col - 2 使得第 2 列位于 centerX
        val x = centerX + (col - 2) * deltaX
        // row - 1 使得第 1 行位于 centerY
        val y = centerY + (row - 1) * deltaY

        return PointF(x, y)
    }

    /**
     * 针对主流屏幕比例进行智能初始化配置
     */
    fun autoFit(width: Int, height: Int) {
        val w = maxOf(width, height)
        val h = minOf(width, height)
        screenWidth = w
        screenHeight = h

        val aspectRatio = w.toFloat() / h.toFloat()

        when {
            // 超宽长屏 20:9 ~ 21:9 (如 2400x1080, 2460x1080)
            aspectRatio >= 2.1f -> {
                centerXPercent = 0.475f
                centerYPercent = 0.450f
                spacingXPercent = 0.076f
                spacingYPercent = 0.155f
            }
            // 主流全面屏 19:9 ~ 20:9 (如 2340x1080, 2400x1080)
            aspectRatio >= 1.9f -> {
                centerXPercent = 0.475f
                centerYPercent = 0.440f
                spacingXPercent = 0.082f
                spacingYPercent = 0.150f
            }
            // 传统 18:9 (2:1)
            aspectRatio >= 1.85f -> {
                centerXPercent = 0.475f
                centerYPercent = 0.440f
                spacingXPercent = 0.086f
                spacingYPercent = 0.152f
            }
            // 传统 16:9 (如 1920x1080, 1280x720)
            aspectRatio >= 1.7f -> {
                centerXPercent = 0.475f
                centerYPercent = 0.430f
                spacingXPercent = 0.093f
                spacingYPercent = 0.150f
            }
            // 平板 16:10 或 4:3 (如 2560x1600, 2048x1536)
            else -> {
                centerXPercent = 0.475f
                centerYPercent = 0.420f
                spacingXPercent = 0.110f
                spacingYPercent = 0.135f
            }
        }
        scale = 1.09f
    }
}
