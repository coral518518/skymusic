package com.skymusic.player.model

/**
 * 代表一个音符打击事件（支持同时按下多个键组成的和弦）
 * @param timeMs 该音符相对于曲目开始的时间戳（毫秒）
 * @param keys 触发的光遇 15 键索引集合（范围 0 ~ 14）
 * @param durationMs 触控时长（毫秒），默认 40ms，足以被游戏引擎响应且不会卡顿
 */
data class NoteEvent(
    val timeMs: Long,
    val keys: List<Int>,
    val durationMs: Long = 40L
) : Comparable<NoteEvent> {
    override fun compareTo(other: NoteEvent): Int {
        return timeMs.compareTo(other.timeMs)
    }
}
