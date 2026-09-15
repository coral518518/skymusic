package com.skymusic.player.parser

import android.util.Log
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.util.UUID

/**
 * 音游伴侣 / 编曲实验室 (compose_lab) 在线乐谱高保真解析器
 * 智能自适应多种数据格式 (包括嵌套声轨 tracks、扁平 songNotes、按键数组与和弦聚合)
 */
object OnlineScoreParser {

    private const val TAG = "OnlineScoreParser"

    fun parse(jsonContent: String, fallbackTitle: String, fallbackBpm: Int = 120): Song {
        val rootElement: JsonElement = try {
            JsonParser.parseString(jsonContent.trim())
        } catch (e: Exception) {
            Log.e(TAG, "Invalid JSON content", e)
            return Song(
                id = UUID.randomUUID().toString(),
                title = fallbackTitle,
                notes = emptyList(),
                bpm = fallbackBpm,
                type = "OnlineMGM"
            )
        }

        var title = fallbackTitle
        var bpm = fallbackBpm
        var artist = "音游伴侣"

        val timeMap = mutableMapOf<Long, MutableSet<Int>>()

        if (rootElement.isJsonObject) {
            val root = rootElement.asJsonObject

            // 提取元数据
            if (root.has("name") && !root.get("name").isJsonNull) {
                title = root.get("name").asString
            } else if (root.has("title") && !root.get("title").isJsonNull) {
                title = root.get("title").asString
            }

            if (root.has("author") && !root.get("author").isJsonNull) {
                artist = root.get("author").asString
            } else if (root.has("creator") && !root.get("creator").isJsonNull) {
                artist = root.get("creator").asString
            }

            if (root.has("bpm") && !root.get("bpm").isJsonNull) {
                val parsedBpm = root.get("bpm").asInt
                if (parsedBpm > 0) bpm = parsedBpm
            }

            // 模式 1: 包含 tracks 声轨数组 (compose_lab 经典多轨合奏格式)
            if (root.has("tracks") && root.get("tracks").isJsonArray) {
                val tracks = root.getAsJsonArray("tracks")
                for (t in tracks) {
                    if (t.isJsonObject) {
                        val trackObj = t.asJsonObject
                        if (trackObj.has("notes") && trackObj.get("notes").isJsonArray) {
                            parseNotesArray(trackObj.getAsJsonArray("notes"), timeMap)
                        }
                    }
                }
            }

            // 模式 2: 包含顶层 notes 或 songNotes 数组
            if (root.has("songNotes") && root.get("songNotes").isJsonArray) {
                parseNotesArray(root.getAsJsonArray("songNotes"), timeMap)
            } else if (root.has("notes") && root.get("notes").isJsonArray) {
                parseNotesArray(root.getAsJsonArray("notes"), timeMap)
            }
        } else if (rootElement.isJsonArray) {
            // 模式 3: 顶层就是数组结构 (如 [ {time, key}, ... ] 或 [ {songNotes:[...]} ])
            val array = rootElement.asJsonArray
            if (array.size() > 0) {
                val first = array.get(0)
                if (first.isJsonObject && first.asJsonObject.has("songNotes")) {
                    val obj = first.asJsonObject
                    if (obj.has("name") && !obj.get("name").isJsonNull) title = obj.get("name").asString
                    if (obj.has("bpm") && !obj.get("bpm").isJsonNull) bpm = obj.get("bpm").asInt
                    parseNotesArray(obj.getAsJsonArray("songNotes"), timeMap)
                } else {
                    parseNotesArray(array, timeMap)
                }
            }
        }

        // 构造按时间递增的 NoteEvent 列表
        val noteEvents = mutableListOf<NoteEvent>()
        for ((timeMs, keys) in timeMap) {
            val sortedKeys = keys.filter { it in 0..14 }.sorted()
            if (sortedKeys.isNotEmpty()) {
                noteEvents.add(NoteEvent(timeMs = timeMs, keys = sortedKeys))
            }
        }
        noteEvents.sort()

        val durationMs = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L

        return Song(
            id = UUID.randomUUID().toString(),
            title = title,
            artist = artist,
            bpm = bpm,
            notes = noteEvents,
            durationMs = durationMs,
            type = "OnlineMGM"
        )
    }

    private fun parseNotesArray(notesArray: JsonArray, timeMap: MutableMap<Long, MutableSet<Int>>) {
        for (i in 0 until notesArray.size()) {
            val item = notesArray.get(i)
            if (!item.isJsonObject) continue
            val obj = item.asJsonObject

            // 时间字段提取 (time, timeMs, t, timestamp)
            val timeMs = when {
                obj.has("time") && !obj.get("time").isJsonNull -> obj.get("time").asLong
                obj.has("timeMs") && !obj.get("timeMs").isJsonNull -> obj.get("timeMs").asLong
                obj.has("t") && !obj.get("t").isJsonNull -> obj.get("t").asLong
                obj.has("timestamp") && !obj.get("timestamp").isJsonNull -> obj.get("timestamp").asLong
                else -> -1L
            }
            if (timeMs < 0L) continue

            val keySet = timeMap.getOrPut(timeMs) { mutableSetOf() }

            // 按键提取:
            // 形式 A: keys 数组 (如 "keys": [0, 4])
            if (obj.has("keys") && obj.get("keys").isJsonArray) {
                val keysArr = obj.getAsJsonArray("keys")
                for (k in keysArr) {
                    val keyIdx = parseSingleKey(k)
                    if (keyIdx in 0..14) keySet.add(keyIdx)
                }
            }

            // 形式 B: 单个 key 字段 (如 "key": 4, "key": "1Key4", "key": "A5")
            if (obj.has("key") && !obj.get("key").isJsonNull) {
                val keyIdx = parseSingleKey(obj.get("key"))
                if (keyIdx in 0..14) keySet.add(keyIdx)
            }

            // 形式 C: pitch 字段 (如 MIDI 音高)
            if (obj.has("pitch") && !obj.get("pitch").isJsonNull) {
                val pitch = obj.get("pitch").asInt
                val keyIdx = pitchToSkyKey(pitch)
                if (keyIdx in 0..14) keySet.add(keyIdx)
            }
        }
    }

    private fun parseSingleKey(elem: JsonElement): Int {
        if (elem.isJsonPrimitive) {
            val prim = elem.asJsonPrimitive
            if (prim.isNumber) {
                val n = prim.asInt
                if (n in 0..14) return n
            } else if (prim.isString) {
                val str = prim.asString.trim()
                // 1Key0 ~ 1Key14
                val match = Regex(""".*Key(\d+)""").find(str)
                if (match != null) {
                    val n = match.groupValues[1].toIntOrNull()
                    if (n != null && n in 0..14) return n
                }
                // 纯数字字符串
                val direct = str.toIntOrNull()
                if (direct != null && direct in 0..14) return direct

                // A1~A5, B1~B5, C1~C5 坐标转换
                val upper = str.uppercase()
                if (upper.length == 2) {
                    val rowChar = upper[0]
                    val colNum = upper[1].digitToIntOrNull() ?: -1
                    if (colNum in 1..5) {
                        val row = when (rowChar) {
                            'A' -> 0
                            'B' -> 1
                            'C' -> 2
                            else -> -1
                        }
                        if (row >= 0) return row * 5 + (colNum - 1)
                    }
                }
            }
        }
        return -1
    }

    private fun pitchToSkyKey(pitch: Int): Int {
        // 标准 C 大调 15 键对应 MIDI 音高 (48 ~ 72)
        val skyMidi = intArrayOf(48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72)
        val idx = skyMidi.indexOf(pitch)
        if (idx != -1) return idx
        // 若八度过高或过低，模 12 对齐自然音阶
        val relative = ((pitch % 12) + 12) % 12
        val majorSteps = intArrayOf(0, 2, 4, 5, 7, 9, 11)
        val step = majorSteps.indexOf(relative)
        return if (step in 0..6) {
            val oct = ((pitch - 48) / 12).coerceIn(0, 1)
            (oct * 7 + step).coerceIn(0, 14)
        } else {
            -1
        }
    }
}
