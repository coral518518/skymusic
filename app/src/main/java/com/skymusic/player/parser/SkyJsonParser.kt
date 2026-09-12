package com.skymusic.player.parser

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.util.UUID

object SkyJsonParser {

    /**
     * 解析 Sky Studio / 光遇社区 JSON 乐谱文本
     */
    fun parse(jsonContent: String, defaultTitle: String = "未命名乐谱"): Song {
        val rootElement: JsonElement = JsonParser.parseString(jsonContent.trim())
        var targetObject: JsonObject? = null
        var songNotesArray: JsonArray? = null
        var title = defaultTitle
        var bpm = 120
        var artist = "光遇玩家"

        if (rootElement.isJsonArray) {
            val array = rootElement.asJsonArray
            if (array.size() > 0) {
                val firstItem = array.get(0)
                if (firstItem.isJsonObject) {
                    val obj = firstItem.asJsonObject
                    if (obj.has("songNotes")) {
                        targetObject = obj
                        songNotesArray = obj.getAsJsonArray("songNotes")
                    } else if (obj.has("time") && obj.has("key")) {
                        // 纯音符数组结构：[{"time":0,"key":"1Key0"}, ...]
                        songNotesArray = array
                    }
                }
            }
        } else if (rootElement.isJsonObject) {
            targetObject = rootElement.asJsonObject
            if (targetObject.has("songNotes")) {
                songNotesArray = targetObject.getAsJsonArray("songNotes")
            }
        }

        if (targetObject != null) {
            if (targetObject.has("name") && !targetObject.get("name").isJsonNull) {
                title = targetObject.get("name").asString
            }
            if (targetObject.has("author") && !targetObject.get("author").isJsonNull) {
                artist = targetObject.get("author").asString
            }
            if (targetObject.has("bpm") && !targetObject.get("bpm").isJsonNull) {
                bpm = targetObject.get("bpm").asInt
            }
        }

        val noteEvents = mutableListOf<NoteEvent>()
        if (songNotesArray != null) {
            // 按照时间将相同时间戳的音符聚合为一个和弦 (Chord)
            val timeMap = mutableMapOf<Long, MutableList<Int>>()

            for (i in 0 until songNotesArray.size()) {
                val item = songNotesArray.get(i)
                if (!item.isJsonObject) continue
                val noteObj = item.asJsonObject

                val time = if (noteObj.has("time")) noteObj.get("time").asLong else 0L
                val keyStr = if (noteObj.has("key")) noteObj.get("key").asString else ""

                val keyIndex = parseKeyIndex(keyStr)
                if (keyIndex in 0..14) {
                    val keyList = timeMap.getOrPut(time) { mutableListOf() }
                    if (!keyList.contains(keyIndex)) {
                        keyList.add(keyIndex)
                    }
                }
            }

            for ((time, keys) in timeMap) {
                noteEvents.add(NoteEvent(timeMs = time, keys = keys.sorted()))
            }
        }

        noteEvents.sort()
        val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L

        return Song(
            id = UUID.randomUUID().toString(),
            title = title,
            artist = artist,
            bpm = bpm,
            notes = noteEvents,
            durationMs = duration,
            type = "SkyJSON"
        )
    }

    /**
     * 解析按键字符格式：
     * "1Key0" -> 0
     * "1Key14" -> 14
     * "Key5" -> 5
     * "2Key3" -> 3
     * "7" -> 7
     */
    fun parseKeyIndex(keyStr: String): Int {
        val clean = keyStr.trim()
        if (clean.isEmpty()) return -1

        // 尝试匹配 "1Key" 后面的数字
        val keyRegex = Regex(""".*Key(\d+)""")
        val match = keyRegex.find(clean)
        if (match != null) {
            val numStr = match.groupValues[1]
            return numStr.toIntOrNull() ?: -1
        }

        // 纯数字匹配
        val directNum = clean.toIntOrNull()
        if (directNum != null && directNum in 0..14) {
            return directNum
        }

        return -1
    }
}
