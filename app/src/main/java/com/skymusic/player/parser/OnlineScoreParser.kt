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
            val meta = extractMetadata(obj, title, artist, bpm)
            title = meta.first
            artist = meta.second
            bpm = meta.third

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
            val meta = extractMetadata(target.asJsonObject, title, artist, bpm)
            title = meta.first
            artist = meta.second
            bpm = meta.third
        }

        // 2. 核心提取：支持多种主流乐谱数据布局
        // 模式 A: 带有 tracks 声轨数组 (compose_lab 经典多轨合奏格式)
        if (target.isJsonObject && target.asJsonObject.has("tracks") && target.asJsonObject.get("tracks").isJsonArray) {
            val tracks = target.asJsonObject.getAsJsonArray("tracks")
            
            // 2.1 检查是否有 solo 声轨
            val hasSolo = tracks.any { it.isJsonObject && it.asJsonObject.has("solo") && it.asJsonObject.get("solo").asBoolean }
            
            // 2.2 过滤静音声轨与打击乐声轨 (避免架子鼓/手鼓等噪音冲入单人钢琴 15 键)
            val candidateTracks = mutableListOf<JsonObject>()
            var nonPercussionCount = 0

            for (t in tracks) {
                if (!t.isJsonObject) continue
                val trackObj = t.asJsonObject
                val isMuted = trackObj.has("muted") && trackObj.get("muted").asBoolean
                if (isMuted) continue
                if (hasSolo && (!trackObj.has("solo") || !trackObj.get("solo").asBoolean)) continue

                val trackName = if (trackObj.has("name") && !trackObj.get("name").isJsonNull) trackObj.get("name").asString.lowercase() else ""
                val instrument = if (trackObj.has("instrument") && !trackObj.get("instrument").isJsonNull) trackObj.get("instrument").asString.lowercase() else ""
                val isPercussion = listOf("drum", "tr_909", "tr-909", "sfx", "dun_dun", "percussion", "cymbal", "鼓", "打击乐", "音效", "排鼓", "手鼓").any {
                    trackName.contains(it) || instrument.contains(it)
                }

                if (!isPercussion) {
                    nonPercussionCount++
                }
                candidateTracks.add(trackObj)
            }

            for (trackObj in candidateTracks) {
                val trackName = if (trackObj.has("name") && !trackObj.get("name").isJsonNull) trackObj.get("name").asString.lowercase() else ""
                val instrument = if (trackObj.has("instrument") && !trackObj.get("instrument").isJsonNull) trackObj.get("instrument").asString.lowercase() else ""
                val isPercussion = listOf("drum", "tr_909", "tr-909", "sfx", "dun_dun", "percussion", "cymbal", "鼓", "打击乐", "音效", "排鼓", "手鼓").any {
                    trackName.contains(it) || instrument.contains(it)
                }

                // 只要存在旋律/钢琴类音轨，就坚决滤除纯打击乐轨
                if (isPercussion && nonPercussionCount > 0) {
                    Log.d(TAG, "Skipping percussion track: $trackName ($instrument)")
                    continue
                }

                for (notesKey in arrayOf("notes", "songNotes", "events", "noteList")) {
                    if (trackObj.has(notesKey) && trackObj.get(notesKey).isJsonArray) {
                        parseNotesArray(trackObj.getAsJsonArray(notesKey), timeMap)
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

            // 1. 优先解析具备专属前缀的原始键标 (0-based: "1Key0"~"1Key14", 以及 "5:1" 键位:声轨格式)
            var keyFound = false
            for (rawProp in arrayOf("rawKey", "raw_key", "raw", "skyKey", "sky_key")) {
                if (obj.has(rawProp) && !obj.get(rawProp).isJsonNull) {
                    val rawElem = obj.get(rawProp)
                    if (rawElem.isJsonPrimitive && rawElem.asJsonPrimitive.isString) {
                        val rawStr = rawElem.asString.trim()
                        // 1Key0 ~ 1Key14 (0-based)
                        val matchKey = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(rawStr)
                        if (matchKey != null) {
                            val k = matchKey.groupValues[1].toIntOrNull()
                            if (k != null && k in 0..14) {
                                keySet.add(k)
                                keyFound = true
                                break
                            }
                        }
                        // "5:1" (0-based col : track)
                        val matchColTrack = Regex("""^(\d+):(\d+)$""").find(rawStr)
                        if (matchColTrack != null) {
                            val k = matchColTrack.groupValues[1].toIntOrNull()
                            if (k != null && k in 0..14) {
                                keySet.add(k)
                                keyFound = true
                                break
                            }
                        }
                    }
                }
            }
            if (keyFound) continue

            // 2. 检查 targetKey (音游伴侣中 1-based: "sky.key.1"~"sky.key.15" 或 "1"~"15" -> 0..14)
            for (targetProp in arrayOf("targetKey", "target_key", "target")) {
                if (obj.has(targetProp) && !obj.get(targetProp).isJsonNull) {
                    val elem = obj.get(targetProp)
                    val k = parseOneBasedKey(elem)
                    if (k in 0..14) {
                        keySet.add(k)
                        keyFound = true
                        break
                    }
                }
            }
            if (keyFound) continue

            // 3. 检查 keyIndex (音游伴侣规范中 1-based: 1..15 -> 0..14)
            for (idxProp in arrayOf("keyIndex", "key_index")) {
                if (obj.has(idxProp) && !obj.get(idxProp).isJsonNull) {
                    val elem = obj.get(idxProp)
                    val k = parseOneBasedKey(elem)
                    if (k in 0..14) {
                        keySet.add(k)
                        keyFound = true
                        break
                    }
                }
            }
            if (keyFound) continue

            // 4. keys 数组 (如 "keys": [1, 4] 或 "key_list": [...])
            for (keysProp in arrayOf("keys", "key_list", "notes", "pitches")) {
                if (obj.has(keysProp) && obj.get(keysProp).isJsonArray) {
                    val arr = obj.getAsJsonArray(keysProp)
                    for (kElem in arr) {
                        val keyIdx = parseSingleKey(kElem)
                        if (keyIdx in 0..14) {
                            keySet.add(keyIdx)
                            keyFound = true
                        }
                    }
                }
            }
            if (keyFound) continue

            // 5. 单个 key / pitch / note 字段
            for (keyProp in arrayOf("rawKey", "key", "pitch", "note", "k", "index", "noteIndex", "code")) {
                if (obj.has(keyProp) && !obj.get(keyProp).isJsonNull) {
                    val keyIdx = parseSingleKey(obj.get(keyProp))
                    if (keyIdx in 0..14) {
                        keySet.add(keyIdx)
                        break
                    }
                }
            }
        }
    }

    private fun extractTime(obj: JsonObject): Long {
        for (timeProp in arrayOf(
            "startMs", "start_ms", "start", "time", "timeMs", "time_ms",
            "t", "timestamp", "offset", "startTime", "start_time", "startTick", "tick"
        )) {
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

    /**
     * 解析音游伴侣 / compose_lab 1-based 按键标示 (1..15 -> 0..14)
     */
    private fun parseOneBasedKey(elem: JsonElement): Int {
        if (!elem.isJsonPrimitive) return -1
        val prim = elem.asJsonPrimitive
        if (prim.isNumber) {
            val n = prim.asInt
            if (n in 1..15) return n - 1
            if (n in 0..14) return n
        } else if (prim.isString) {
            val str = prim.asString.trim()
            val match = Regex(""".*key\.(\d+)""", RegexOption.IGNORE_CASE).find(str)
            if (match != null) {
                val n = match.groupValues[1].toIntOrNull()
                if (n != null && n in 1..15) return n - 1
            }
            val direct = str.toIntOrNull()
            if (direct != null) {
                if (direct in 1..15) return direct - 1
                if (direct in 0..14) return direct
            }
        }
        return -1
    }

    /**
     * 全面兼容的单个按键通用提取
     */
    private fun parseSingleKey(elem: JsonElement): Int {
        if (elem.isJsonPrimitive) {
            val prim = elem.asJsonPrimitive
            if (prim.isNumber) {
                val n = prim.asInt
                // 优先 1..15 (音游伴侣规范中 pitch 与 key 绝大多数为 1-based)
                if (n in 1..15) return n - 1
                if (n in 0..14) return n
                // 如果是 MIDI 音高 (48..84)
                return pitchToSkyKey(n)
            } else if (prim.isString) {
                val str = prim.asString.trim()
                // "1Key0" ~ "1Key14" (0-based)
                val match = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(str)
                if (match != null) {
                    val n = match.groupValues[1].toIntOrNull()
                    if (n != null && n in 0..14) return n
                }

                // "sky.key.1" ~ "sky.key.15" (1-based -> 0-based)
                val skyMatch = Regex(""".*key\.(\d+)""", RegexOption.IGNORE_CASE).find(str)
                if (skyMatch != null) {
                    val n = skyMatch.groupValues[1].toIntOrNull()
                    if (n != null && n in 1..15) return n - 1
                }

                // "5:1" 格式 (0-based col : track)
                val colMatch = Regex("""^(\d+):(\d+)$""").find(str)
                if (colMatch != null) {
                    val n = colMatch.groupValues[1].toIntOrNull()
                    if (n != null && n in 0..14) return n
                }

                // 纯数字字符串：在音游伴侣中均为 1..15
                val direct = str.toIntOrNull()
                if (direct != null) {
                    if (direct in 1..15) return direct - 1
                    if (direct in 0..14) return direct
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
        // 标准 C4 黄金音域 15 键 (60 ~ 84)
        val skyMidiC4 = intArrayOf(60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84)
        val idxC4 = skyMidiC4.indexOf(pitch)
        if (idxC4 != -1) return idxC4

        // 标准 C3 低音区 15 键 (48 ~ 72)
        val skyMidiC3 = intArrayOf(48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72)
        val idxC3 = skyMidiC3.indexOf(pitch)
        if (idxC3 != -1) return idxC3

        // 若八度过高或过低，模 12 对齐自然大调音阶
        val relative = ((pitch % 12) + 12) % 12
        val majorSteps = intArrayOf(0, 2, 4, 5, 7, 9, 11)
        val step = majorSteps.indexOf(relative)
        return if (step in 0..6) {
            val oct = ((pitch - 60) / 12).coerceIn(0, 1)
            (oct * 7 + step).coerceIn(0, 14)
        } else {
            -1
        }
    }

    private fun extractMetadata(
        obj: JsonObject,
        currentTitle: String,
        currentArtist: String,
        currentBpm: Int
    ): Triple<String, String, Int> {
        var title = currentTitle
        var artist = currentArtist
        var bpm = currentBpm

        fun check(o: JsonObject) {
            if (o.has("name") && !o.get("name").isJsonNull) title = o.get("name").asString
            if (o.has("title") && !o.get("title").isJsonNull) title = o.get("title").asString
            if (o.has("songName") && !o.get("songName").isJsonNull) title = o.get("songName").asString
            if (o.has("author") && !o.get("author").isJsonNull) artist = o.get("author").asString
            if (o.has("creator") && !o.get("creator").isJsonNull) artist = o.get("creator").asString
            if (o.has("artist") && !o.get("artist").isJsonNull) artist = o.get("artist").asString
            if (o.has("bpm") && !o.get("bpm").isJsonNull) {
                val b = o.get("bpm").asInt
                if (b > 0) bpm = b
            }
        }

        check(obj)
        if (obj.has("metadata") && obj.get("metadata").isJsonObject) {
            check(obj.getAsJsonObject("metadata"))
        }
        if (obj.has("score") && obj.get("score").isJsonObject) {
            val scoreObj = obj.getAsJsonObject("score")
            check(scoreObj)
            if (scoreObj.has("metadata") && scoreObj.get("metadata").isJsonObject) {
                check(scoreObj.getAsJsonObject("metadata"))
            }
        }
        return Triple(title, artist, bpm)
    }
}
