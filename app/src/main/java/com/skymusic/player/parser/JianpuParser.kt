package com.skymusic.player.parser

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.util.UUID

object JianpuParser {

    /**
     * 解析简谱文本 (如 "1 2 3 1 | 1 2 3 1 | 3 4 5 - | (1 3 5)")
     * 基础拍速 120 BPM，每拍 500ms
     */
    fun parse(text: String, defaultTitle: String = "简谱乐曲"): Song {
        val noteEvents = mutableListOf<NoteEvent>()
        var currentTime = 0L
        val beatDuration = 500L // 默认每四分音符 500ms (120 BPM)

        // 预处理：去掉小节线 |，把换行转为空格
        val sanitized = text.replace("|", " ")
            .replace("\r", " ")
            .replace("\n", " ")
            .trim()

        val tokens = sanitized.split(Regex("""\s+""")).filter { it.isNotEmpty() }

        var i = 0
        while (i < tokens.size) {
            val token = tokens[i]

            // 和弦匹配：如 [1,3,5] 或 (1,3,5)
            if (token.startsWith("(") || token.startsWith("[")) {
                var chordStr = token
                while (!chordStr.endsWith(")") && !chordStr.endsWith("]") && i + 1 < tokens.size) {
                    i++
                    chordStr += " " + tokens[i]
                }
                val cleanNotes = chordStr.replace("(", "").replace(")", "")
                    .replace("[", "").replace("]", "")
                    .split(Regex("""[, \s]+"""))

                val keys = cleanNotes.mapNotNull { parseNoteToKey(it) }.distinct()
                if (keys.isNotEmpty()) {
                    noteEvents.add(NoteEvent(currentTime, keys))
                }
                currentTime += beatDuration
            } else if (token == "-" || token == "——") {
                // 延音线，延长上一拍
                currentTime += beatDuration
            } else if (token == "0") {
                // 休止符
                currentTime += beatDuration
            } else {
                val key = parseNoteToKey(token)
                if (key != null) {
                    noteEvents.add(NoteEvent(currentTime, listOf(key)))
                }
                currentTime += beatDuration
            }
            i++
        }

        noteEvents.sort()
        val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 800L else 0L

        return Song(
            id = UUID.randomUUID().toString(),
            title = defaultTitle,
            artist = "简谱转换",
            bpm = 120,
            notes = noteEvents,
            durationMs = duration,
            type = "Jianpu"
        )
    }

    private fun parseNoteToKey(token: String): Int? {
        val t = token.trim()
        if (t.isEmpty()) return null

        // ++1 或 +1. -> Key 14
        if (t.startsWith("++") || t.startsWith("+1.")) {
            return 14
        }

        // 高音区 +1 ~ +7 或 1. ~ 7. -> Keys 7 ~ 13
        if (t.startsWith("+")) {
            val num = t.substring(1).toIntOrNull()
            if (num in 1..7) return (num!! - 1) + 7
        }
        if (t.endsWith(".") && !t.startsWith(".")) {
            val num = t.substring(0, t.length - 1).toIntOrNull()
            if (num in 1..7) return (num!! - 1) + 7
        }

        // 中/低音区 1 ~ 7 -> Keys 0 ~ 6
        val num = t.toIntOrNull()
        if (num in 1..7) {
            return num!! - 1
        }

        // 也支持直接写光遇键位：1Key0 ~ 1Key14
        if (t.contains("Key")) {
            return SkyJsonParser.parseKeyIndex(t).takeIf { it in 0..14 }
        }

        return null
    }
}
