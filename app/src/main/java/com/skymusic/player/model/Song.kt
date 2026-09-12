package com.skymusic.player.model

/**
 * 乐谱通用模型
 */
data class Song(
    val id: String,
    val title: String,
    val artist: String = "未知",
    val bpm: Int = 120,
    val notes: List<NoteEvent> = emptyList(),
    val durationMs: Long = 0L,
    val isPreset: Boolean = false,
    val type: String = "JSON" // JSON, MIDI, TXT
) {
    val noteCount: Int
        get() = notes.sumOf { it.keys.size }

    fun getFormattedDuration(): String {
        val totalSec = durationMs / 1000
        val min = totalSec / 60
        val sec = totalSec % 60
        return String.format("%02d:%02d", min, sec)
    }
}
