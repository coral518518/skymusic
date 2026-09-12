package com.skymusic.player.ui

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.View
import com.skymusic.player.engine.KeyLayoutManager

class KeyVisualizerView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val layoutManager = KeyLayoutManager.getInstance(context)

    // 外圈画笔（琥珀金 - 钢琴按键边界判定圈）
    private val outerStrokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FFD54F")
        style = Paint.Style.STROKE
        strokeWidth = 2.5f * resources.displayMetrics.density
    }

    // 防检测随机点击真实范围圈画笔（青蓝虚线内圈）
    private val innerJitterPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#80D8FF")
        style = Paint.Style.STROKE
        strokeWidth = 1.6f * resources.displayMetrics.density
        pathEffect = DashPathEffect(
            floatArrayOf(5f * resources.displayMetrics.density, 3.5f * resources.displayMetrics.density),
            0f
        )
    }

    // 打击高亮脉冲画笔（青蓝发光，仅在击键瞬间闪烁，平时零遮挡）
    private val activeFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#8080D8FF")
        style = Paint.Style.FILL
    }

    // 中心微型十字准星画笔
    private val centerCrossPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#B3FFFFFF")
        strokeWidth = 1.2f * resources.displayMetrics.density
    }

    // 按键编号文字画笔
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 13f * resources.displayMetrics.scaledDensity
        textAlign = Paint.Align.CENTER
        setShadowLayer(3f, 0f, 1.5f, Color.BLACK)
    }

    private val activeKeys = mutableSetOf<Int>()

    // 音符唱名表
    private val noteLabels = arrayOf(
        "1", "2", "3", "4", "5",
        "6", "7", "+1", "+2", "+3",
        "+4", "+5", "+6", "+7", "++1"
    )

    fun setActiveKeys(keys: Collection<Int>) {
        activeKeys.clear()
        activeKeys.addAll(keys)
        postInvalidate()
    }

    fun clearActiveKeys() {
        if (activeKeys.isNotEmpty()) {
            activeKeys.clear()
            postInvalidate()
        }
    }

    fun refreshLayout() {
        postInvalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val density = resources.displayMetrics.density
        val baseRadius = layoutManager.config.keyRadiusDp * density * layoutManager.config.scale
        // 防检测真实随机落点散布范围圈（按键半径的 45%）
        val jitterRadius = baseRadius * 0.45f
        val crossLen = 3.5f * density

        for (i in 0..14) {
            val pt = layoutManager.getKeyPosition(i)
            val isActive = activeKeys.contains(i)

            // 1. 敲击触发时短暂高亮发光；平时完全透明镂空，不遮挡游戏画面按键！
            if (isActive) {
                canvas.drawCircle(pt.x, pt.y, baseRadius * 1.05f, activeFillPaint)
            }

            // 2. 绘制黄色外圈（按键边界圈）
            canvas.drawCircle(pt.x, pt.y, baseRadius, outerStrokePaint)

            // 3. 绘制青蓝虚线内圈（防检测随机点击真实落点范围圈）
            canvas.drawCircle(pt.x, pt.y, jitterRadius, innerJitterPaint)

            // 4. 绘制中心微十字准星标定真实物理中心
            canvas.drawLine(pt.x - crossLen, pt.y, pt.x + crossLen, pt.y, centerCrossPaint)
            canvas.drawLine(pt.x, pt.y - crossLen, pt.x, pt.y + crossLen, centerCrossPaint)

            // 5. 绘制中心标注音符文字 (如 "1", "+1")
            val label = if (i in noteLabels.indices) noteLabels[i] else "$i"
            val textY = pt.y - (textPaint.descent() + textPaint.ascent()) / 2
            canvas.drawText(label, pt.x, textY, textPaint)
        }
    }
}
