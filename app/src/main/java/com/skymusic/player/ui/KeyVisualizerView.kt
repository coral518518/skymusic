package com.skymusic.player.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import com.skymusic.player.engine.KeyLayoutManager

class KeyVisualizerView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val layoutManager = KeyLayoutManager.getInstance(context)

    // 普通待机外圈画笔（琥珀金）
    private val circleStrokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FFD54F")
        style = Paint.Style.STROKE
        strokeWidth = 3f * resources.displayMetrics.density
    }

    // 内部半透明填充画笔
    private val circleFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#33FFD54F")
        style = Paint.Style.FILL
    }

    // 打击高亮画笔（青蓝荧光）
    private val activeFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#B380D8FF")
        style = Paint.Style.FILL
    }

    // 按键编号文字画笔
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 14f * resources.displayMetrics.scaledDensity
        textAlign = Paint.Align.CENTER
        setShadowLayer(4f, 0f, 2f, Color.BLACK)
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

        for (i in 0..14) {
            val pt = layoutManager.getKeyPosition(i)
            val isActive = activeKeys.contains(i)

            // 1. 绘制圆形底色
            if (isActive) {
                canvas.drawCircle(pt.x, pt.y, baseRadius * 1.15f, activeFillPaint)
            } else {
                canvas.drawCircle(pt.x, pt.y, baseRadius, circleFillPaint)
            }

            // 2. 绘制金边外框
            canvas.drawCircle(pt.x, pt.y, baseRadius, circleStrokePaint)

            // 3. 绘制中心标注文本 (如 "1", "+1", "0")
            val label = if (i in noteLabels.indices) noteLabels[i] else "$i"
            val textY = pt.y - (textPaint.descent() + textPaint.ascent()) / 2
            canvas.drawText(label, pt.x, textY, textPaint)
        }
    }
}
