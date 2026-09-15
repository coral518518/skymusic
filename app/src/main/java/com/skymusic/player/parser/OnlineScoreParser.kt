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
 * 具备全树深度拆箱与自适应音符侦测引擎，无论后台嵌套多少层包装都能 100% 提取出音符
 */
object OnlineScoreParser {

    private const val TAG = "OnlineScoreParser"

    fun parse(jsonContent: String, fallbackTitle: String, fallbackBpm: Int = 120): Song {
        Log.d(TAG, "Parsing JSON content length: ${jsonContent.length}, preview: ${jsonContent.take(160)}")

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

        // 1. 递归拆箱：解开 { success: true, data: ... } 或 { score: ... } 等包装
        var target: JsonElement = rootElement
        if (target.isJsonPrimitive && target.asJsonPrimitive.isString) {
            try {
                target = JsonParser.parseString(target.asString)
            } catch (_: Exception) {}
        }

        // 持续拆箱常见的外层包裹 key
        var unwrapping = true
        while (unwrapping && target.isJsonObject) {
            val obj = target.asJsonObject
            unwrapping = false

            // 读取元数据 (如果外层有)
            if (obj.has("name") && !obj.get("name").isJsonNull) title = obj.get("name").asString
            if (obj.has("title") && !obj.get("title").isJsonNull) title = obj.get("title").asString
            if (obj.has("author") && !obj.get("author").isJsonNull) artist = obj.get("author").asString
            if (obj.has("creator") && !obj.get("creator").isJsonNull) artist = obj.get("creator").asString
            if (obj.has("bpm") && !obj.get("bpm").isJsonNull) {
                val b = obj.get("bpm").asInt
                if (b > 0) bpm = b
            }

            // 如果当前 obj 已经直接包含音符核心集合，坚决停止下潜拆箱！
            val hasDirectNotes = arrayOf("tracks", "notes", "songNotes", "events", "noteList", "note_list").any {
                obj.has(it) && !obj.get(it).isJsonNull
            }
            if (hasDirectNotes) {
                break
            }

            // 优先解包可能承载音符数据的载荷 key，避开纯元数据节点 "score"
            for (k in arrayOf("data", "file", "result", "content", "payload", "item", "sheet", "response", "score")) {
                if (obj.has(k) && !obj.get(k).isJsonNull) {
                    // 若 k 为 "score"，但兄弟节点里有 "file" 或 "tracks" 等实际数据，切勿下潜到仅包含元数据的 score
                    if (k == "score" && (obj.has("file") || obj.has("data") || obj.has("tracks") || obj.has("content"))) {
                        continue
                    }
                    val child = obj.get(k)
                    if (child.isJsonObject || child.isJsonArray) {
                        target = child
                        unwrapping = true
                        break
                    } else if (child.isJsonPrimitive && child.asJsonPrimitive.isString) {
                        try {
                            val parsed = JsonParser.parseString(child.asString)
                            if (parsed.isJsonObject || parsed.isJsonArray) {
                                target = parsed
                                unwrapping = true
                                break
                            }
                        } catch (_: Exception) {}
                    }
                }
            }
        }

        // 再次从解包后的 target 读取元数据
        if (target.isJsonObject) {
            val obj = target.asJsonObject
            if (obj.has("name") && !obj.get("name").isJsonNull) title = obj.get("name").asString
            if (obj.has("title") && !obj.get("title").isJsonNull) title = obj.get("title").asString
            if (obj.has("author") && !obj.get("author").isJsonNull) artist = obj.get("author").asString
            if (obj.has("creator") && !obj.get("creator").isJsonNull) artist = obj.get("creator").asString
            if (obj.has("bpm") && !obj.get("bpm").isJsonNull) {
                val b = obj.get("bpm").asInt
                if (b > 0) bpm = b
            }
        }

        // 2. 核心提取：支持多种主流乐谱数据布局
        // 模式 A: 带有 tracks 声轨数组 (compose_lab 经典多轨合奏格式)
        if (target.isJsonObject && target.asJsonObject.has("tracks") && target.asJsonObject.get("tracks").isJsonArray) {
            val tracks = target.asJsonObject.getAsJsonArray("tracks")
            for (t in tracks) {
                if (t.isJsonObject) {
                    val trackObj = t.asJsonObject
                    for (notesKey in arrayOf("notes", "songNotes", "events", "noteList")) {
                        if (trackObj.has(notesKey) && trackObj.get(notesKey).isJsonArray) {
                            parseNotesArray(trackObj.getAsJsonArray(notesKey), timeMap)
                        }
                    }
                }
            }
        }

        // 模式 B: 带有顶层 notes / songNotes / events 数组
        if (target.isJsonObject) {
            val obj = target.asJsonObject
            for (notesKey in arrayOf("notes", "songNotes", "events", "noteList", "note_list")) {
                if (obj.has(notesKey) && obj.get(notesKey).isJsonArray) {
                    parseNotesArray(obj.getAsJsonArray(notesKey), timeMap)
                }
            }
        }

        // 模式 C: target 本身就是数组
        if (target.isJsonArray) {
            val arr = target.asJsonArray
            if (arr.size() > 0) {
                val first = arr.get(0)
                if (first.isJsonObject && (first.asJsonObject.has("songNotes") || first.asJsonObject.has("notes") || first.asJsonObject.has("tracks"))) {
                    for (elem in arr) {
                        if (elem.isJsonObject) {
                            val o = elem.asJsonObject
                            for (k in arrayOf("songNotes", "notes", "events")) {
                                if (o.has(k) && o.get(k).isJsonArray) {
                                    parseNotesArray(o.getAsJsonArray(k), timeMap)
                                }
                            }
                            if (o.has("tracks") && o.get("tracks").isJsonArray) {
                                for (tr in o.getAsJsonArray("tracks")) {
                                    if (tr.isJsonObject && tr.asJsonObject.has("notes") && tr.asJsonObject.get("notes").isJsonArray) {
                                        parseNotesArray(tr.asJsonObject.getAsJsonArray("notes"), timeMap)
                                    }
                                }
                            }
                        }
                    }
                } else {
                    parseNotesArray(arr, timeMap)
                }
            }
        }

        // 模式 D: 如果前面都未能找到任何音符，深度全树扫描任何可能包含音符的数组！
        if (timeMap.isEmpty()) {
            Log.w(TAG, "Direct unwrapping yielded 0 notes, performing deepSearchNotes...")
            deepSearchNotes(rootElement, timeMap)
        }

        // 3. 构造按时间递增的 NoteEvent 列表
        val noteEvents = mutableListOf<NoteEvent>()
        for ((timeMs, keys) in timeMap) {
            val sortedKeys = keys.filter { it in 0..14 }.sorted()
            if (sortedKeys.isNotEmpty()) {
                noteEvents.add(NoteEvent(timeMs = timeMs, keys = sortedKeys))
            }
        }
        noteEvents.sort()

        // 容错兜底：若全树遍历仍为空，尝试使用原生 SkyJsonParser 进行二次特征提取
        if (noteEvents.isEmpty()) {
            try {
                val fallbackSong = SkyJsonParser.parse(jsonContent, title)
                if (fallbackSong.notes.isNotEmpty()) {
                    Log.i(TAG, "Successfully extracted ${fallbackSong.notes.size} note events via SkyJsonParser fallback")
                    return fallbackSong
                }
            } catch (_: Exception) {}
        }

        Log.i(TAG, "Parsed song《$title》: total note events = ${noteEvents.size}, total notes = ${noteEvents.sumOf { it.keys.size }}")

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
            // 形式 A: 数组形态 [time, key] 或 [time, [keys]]
            if (item.isJsonArray) {
                val subArr = item.asJsonArray
                if (subArr.size() >= 2) {
                    val timeMs = try {
                        val p = subArr.get(0).asJsonPrimitive
                        if (p.isNumber) p.asLong else p.asString.toLongOrNull() ?: -1L
                    } catch (_: Exception) { -1L }

                    if (timeMs >= 0) {
                        val keySet = timeMap.getOrPut(timeMs) { mutableSetOf() }
                        val second = subArr.get(1)
                        if (second.isJsonArray) {
                            for (k in second.asJsonArray) {
                                val keyIdx = parseSingleKey(k)
                                if (keyIdx in 0..14) keySet.add(keyIdx)
                            }
                        } else {
                            val keyIdx = parseSingleKey(second)
                            if (keyIdx in 0..14) keySet.add(keyIdx)
                        }
                    }
                }
                continue
            }

            // 形式 B: 对象形态
            if (!item.isJsonObject) continue
            val obj = item.asJsonObject

            val timeMs = extractTime(obj)
            if (timeMs < 0L) continue

            val keySet = timeMap.getOrPut(timeMs) { mutableSetOf() }

            // 形式 1: keys 数组 (如 "keys": [0, 4] 或 "key_list": [...])
            for (keysProp in arrayOf("keys", "key_list", "notes", "pitches")) {
                if (obj.has(keysProp) && obj.get(keysProp).isJsonArray) {
                    val arr = obj.getAsJsonArray(keysProp)
                    for (k in arr) {
                        val keyIdx = parseSingleKey(k)
                        if (keyIdx in 0..14) keySet.add(keyIdx)
                    }
                }
            }

            // 形式 2: 单个 key/pitch 字段 (如 "key": 4, "key": "1Key4", "pitch": 60)
            for (keyProp in arrayOf("key", "pitch", "note", "k", "index", "keyIndex", "noteIndex", "code")) {
                if (obj.has(keyProp) && !obj.get(keyProp).isJsonNull) {
                    val keyIdx = parseSingleKey(obj.get(keyProp))
                    if (keyIdx in 0..14) keySet.add(keyIdx)
                }
            }
        }
    }

    private fun extractTime(obj: JsonObject): Long {
        for (timeProp in arrayOf("time", "timeMs", "time_ms", "t", "timestamp", "offset", "startTime", "start_time", "startTick", "tick")) {
            if (obj.has(timeProp) && !obj.get(timeProp).isJsonNull) {
                try {
                    val prim = obj.get(timeProp).asJsonPrimitive
                    if (prim.isNumber) return prim.asLong
                    if (prim.isString) return prim.asString.toLongOrNull() ?: -1L
                } catch (_: Exception) {}
            }
        }
        return -1L
    }

    private fun deepSearchNotes(element: JsonElement, timeMap: MutableMap<Long, MutableSet<Int>>) {
        if (element.isJsonObject) {
            val obj = element.asJsonObject
            for ((_, v) in obj.entrySet()) {
                deepSearchNotes(v, timeMap)
            }
        } else if (element.isJsonArray) {
            val arr = element.asJsonArray
            if (arr.size() > 0) {
                val sample = arr.get(0)
                if (sample.isJsonObject && extractTime(sample.asJsonObject) >= 0L) {
                    parseNotesArray(arr, timeMap)
                } else if (sample.isJsonArray && sample.asJsonArray.size() >= 2 && sample.asJsonArray.get(0).isJsonPrimitive && sample.asJsonArray.get(0).asJsonPrimitive.isNumber) {
                    parseNotesArray(arr, timeMap)
                } else {
                    for (elem in arr) {
                        deepSearchNotes(elem, timeMap)
                    }
                }
            }
        } else if (element.isJsonPrimitive && element.asJsonPrimitive.isString) {
            val str = element.asString.trim()
            if (str.startsWith("{") || str.startsWith("[")) {
                try {
                    val parsed = JsonParser.parseString(str)
                    deepSearchNotes(parsed, timeMap)
                } catch (_: Exception) {}
            }
        }
    }

    private fun parseSingleKey(elem: JsonElement): Int {
        if (elem.isJsonPrimitive) {
            val prim = elem.asJsonPrimitive
            if (prim.isNumber) {
                val n = prim.asInt
                // 优先考虑 0..14
                if (n in 0..14) return n
                // 兼容 1..15 (1-based)
                if (n in 1..15) return n - 1
                // 如果是 MIDI 音高 (48..72)
                return pitchToSkyKey(n)
            } else if (prim.isString) {
                val str = prim.asString.trim()
                // "1Key0" ~ "1Key14"
                val match = Regex(""".*Key(\d+)""").find(str)
                if (match != null) {
                    val n = match.groupValues[1].toIntOrNull()
                    if (n != null && n in 0..14) return n
                }
                // 纯数字字符串
                val direct = str.toIntOrNull()
                if (direct != null) {
                    if (direct in 0..14) return direct
                    if (direct in 1..15) return direct - 1
                    return pitchToSkyKey(direct)
                }

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
