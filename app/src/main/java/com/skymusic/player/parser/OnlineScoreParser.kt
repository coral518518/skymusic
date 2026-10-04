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
 * 全能统一乐谱解析器 (Universal Unified Score Parser - Schema-Driven)
 * 采用【根据关键字段特征签名分流 (Schema Dispatcher)】架构，彻底消灭模糊数值推测带来的误判与失准。
 *
 * 支持三大独立标准规范通道：
 * 1. [ScoreFormat.MGM_SCORE]：音游伴侣官方规范 (包含 format=="mgm.score" 或 tracks 数组)
 *    - 严格按官方规范：唯一认准 targetKey ("sky.key.1"~"15") 或 keyIndex/pitch (1..15 -> key - 1)
 *    - 时间严格为 startMs (绝对毫秒，微秒级对齐)
 *    - 多轨声部智能降噪：多轨合奏时自动剔除纯打击乐/架子鼓 (drum/percussion/sfx/鼓/打击乐)
 *
 * 2. [ScoreFormat.SKY_STUDIO]：光遇社区 SkyStudio 规范 (包含 songNotes 数组与 bpm/bitsPerPage)
 *    - 严格按 SkyStudio 规范：键位认准 "1Key0"~"1Key14"，天然 0-based，直接提取纯数字，绝不二次减 1
 *    - 时间读取 time 毫秒
 *    - 自动识别 16 分音符网格槽位序号 (0, 1, 2, 3...) 并依据 BPM 转换为真实毫秒
 *
 * 3. [ScoreFormat.GENERIC_RAW]：极简纯音符序列 / 第三方转换器导出
 *    - 包含纯数组 [ { "time": 0, "key": ... } ]
 *    - 兼容字母简谱 ("A1"~"C5") 与纯数字自适应
 *
 * 4. 全局微和弦智能聚合 (Anti-Queue Congestion)：
 *    - 对多轨落差 <= 12ms 的近邻音符聚合成同拍和弦，彻底根除系统无障碍手势队列阻塞引发的节奏崩坏
 */
object OnlineScoreParser {

    private const val TAG = "UnifiedScoreParser"

    enum class ScoreFormat {
        MGM_SCORE,
        SKY_STUDIO,
        GENERIC_RAW
    }

    private val PERCUSSION_KEYWORDS = listOf(
        "drum", "tr_909", "sfx", "percussion", "perc",
        "鼓", "打击乐", "架子鼓", "军鼓", "底鼓", "镲", "铃铛"
    )

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
                type = "UnifiedJSON"
            )
        }

        // 1. 递归拆解最外层字符串嵌套
        var current: JsonElement = rootElement
        if (current.isJsonPrimitive && current.asJsonPrimitive.isString) {
            try {
                current = JsonParser.parseString(current.asString.trim())
            } catch (_: Exception) {}
        }

        // 2. 解包外层包装 (如 { "success": true, "data": { "score": ... } })
        val (scoreObj, notesArray) = unpackRoot(current)

        // 3. 根据核心字段签名精准识别乐谱格式类型 (Schema Discrimination)
        val format = detectScoreFormat(scoreObj, notesArray, current)
        Log.i(TAG, "🎯 乐谱《$fallbackTitle》结构特征签名判定为: $format")

        // 4. 按各自官方独立规范通道分流解析
        return when (format) {
            ScoreFormat.MGM_SCORE -> parseMgmScore(scoreObj, notesArray, fallbackTitle, fallbackBpm)
            ScoreFormat.SKY_STUDIO -> parseSkyStudioScore(scoreObj, notesArray, fallbackTitle, fallbackBpm)
            ScoreFormat.GENERIC_RAW -> parseGenericRawScore(scoreObj, notesArray, current, fallbackTitle, fallbackBpm)
        }
    }

    /**
     * 智能拆箱：将嵌套的 data/score 对象与顶层数组分离
     */
    private fun unpackRoot(current: JsonElement): Pair<JsonObject?, JsonArray?> {
        var scoreObj: JsonObject? = null
        var notesArray: JsonArray? = null

        if (current.isJsonObject) {
            var target = current.asJsonObject
            while (true) {
                if (target.has("tracks") || target.has("notes") || target.has("songNotes") || target.has("format")) {
                    break
                }
                val dataChild = target.get("data")
                if (dataChild != null && dataChild.isJsonObject) {
                    target = dataChild.asJsonObject
                    continue
                }
                val scoreChild = target.get("score")
                if (scoreChild != null && scoreChild.isJsonObject) {
                    target = scoreChild.asJsonObject
                    continue
                }
                break
            }
            scoreObj = target
        } else if (current.isJsonArray) {
            val array = current.asJsonArray
            if (array.size() > 0) {
                val first = array.get(0)
                if (first.isJsonObject) {
                    val obj = first.asJsonObject
                    if (obj.has("songNotes") || obj.has("tracks") || obj.has("bpm") || obj.has("name") || obj.has("bitsPerPage")) {
                        scoreObj = obj
                    } else if (obj.has("time") || obj.has("startMs") || obj.has("key") || obj.has("targetKey")) {
                        notesArray = array
                    }
                }
            }
        }

        return Pair(scoreObj, notesArray)
    }

    /**
     * 根据关键字段特征签名判定具体格式类型
     */
    private fun detectScoreFormat(scoreObj: JsonObject?, notesArray: JsonArray?, root: JsonElement): ScoreFormat {
        if (scoreObj != null) {
            // 特征 1: 带有 format == "mgm.score" 或带有 "tracks" 轨道列表
            if (scoreObj.has("format") && scoreObj.get("format").isJsonPrimitive) {
                if (scoreObj.get("format").asString.contains("mgm.score", ignoreCase = true)) {
                    return ScoreFormat.MGM_SCORE
                }
            }
            if (scoreObj.has("tracks") && scoreObj.get("tracks").isJsonArray) {
                return ScoreFormat.MGM_SCORE
            }

            // 特征 2: 带有 "songNotes" 且带有 "bpm" 或 "bitsPerPage" -> SkyStudio 标准
            if (scoreObj.has("songNotes") && scoreObj.get("songNotes").isJsonArray) {
                return ScoreFormat.SKY_STUDIO
            }

            // 特征 3: 顶层带有 notes 数组
            if (scoreObj.has("notes") && scoreObj.get("notes").isJsonArray) {
                val arr = scoreObj.getAsJsonArray("notes")
                if (arr.size() > 0 && arr.get(0).isJsonObject) {
                    val sample = arr.get(0).asJsonObject
                    if (sample.has("targetKey") || sample.has("startMs") || sample.has("keyIndex") || sample.has("pitch")) {
                        return ScoreFormat.MGM_SCORE
                    }
                }
                return ScoreFormat.GENERIC_RAW
            }
        }

        if (notesArray != null && notesArray.size() > 0 && notesArray.get(0).isJsonObject) {
            val sample = notesArray.get(0).asJsonObject
            if (sample.has("targetKey") || sample.has("startMs") || sample.has("keyIndex") || sample.has("pitch")) {
                return ScoreFormat.MGM_SCORE
            }
            if (sample.has("key") && sample.get("key").asString.contains("Key", ignoreCase = true)) {
                return ScoreFormat.SKY_STUDIO
            }
        }

        return ScoreFormat.GENERIC_RAW
    }

    // ========================================================================
    // 通道 1: 音游伴侣官方规范解析器 (MGM_SCORE)
    // ========================================================================
    private fun parseMgmScore(
        scoreObj: JsonObject?,
        directNotesArray: JsonArray?,
        fallbackTitle: String,
        fallbackBpm: Int
    ): Song {
        var title = fallbackTitle
        var bpm = fallbackBpm
        var artist = "音游伴侣"

        if (scoreObj != null) {
            val metaTitle = getJsonString(scoreObj, "name", "title")
            if (metaTitle.isNotBlank()) title = metaTitle

            val metaArtist = getJsonString(scoreObj, "artist", "author", "creator")
            if (metaArtist.isNotBlank()) artist = metaArtist

            val b = getJsonInt(scoreObj, "bpm")
            if (b > 0) bpm = b

            if (scoreObj.has("metadata") && scoreObj.get("metadata").isJsonObject) {
                val meta = scoreObj.getAsJsonObject("metadata")
                val t = getJsonString(meta, "title", "name")
                if (t.isNotBlank()) title = t
                val a = getJsonString(meta, "artist", "author", "creator")
                if (a.isNotBlank()) artist = a
                val mb = getJsonInt(meta, "bpm")
                if (mb > 0) bpm = mb
            }
        }

        val rawItems = mutableListOf<Pair<Long, Int>>()

        if (scoreObj != null && scoreObj.has("tracks") && scoreObj.get("tracks").isJsonArray) {
            val tracks = scoreObj.getAsJsonArray("tracks")
            val hasMultipleTracks = tracks.size() > 1

            for (t in tracks) {
                if (!t.isJsonObject) continue
                val trackObj = t.asJsonObject
                if (trackObj.has("muted") && trackObj.get("muted").asBoolean) continue

                // 官方多声轨智能过滤：过滤纯打击乐/节奏轨
                if (hasMultipleTracks && isPercussionTrack(trackObj)) {
                    Log.d(TAG, "[MGM] 忽略伴奏打击乐声部: ${trackObj.get("name")?.asString}")
                    continue
                }

                val notes = if (trackObj.has("notes") && trackObj.get("notes").isJsonArray) {
                    trackObj.getAsJsonArray("notes")
                } else if (trackObj.has("songNotes") && trackObj.get("songNotes").isJsonArray) {
                    trackObj.getAsJsonArray("songNotes")
                } else null

                if (notes != null) {
                    for (i in 0 until notes.size()) {
                        val item = notes.get(i)
                        if (!item.isJsonObject) continue
                        val n = item.asJsonObject
                        val timeMs = extractMgmTime(n)
                        if (timeMs < 0L) continue
                        val key = extractMgmKeyIndex(n)
                        if (key in 0..14) {
                            rawItems.add(Pair(timeMs, key))
                        }
                    }
                }
            }
        }

        // 顶层单轨 notes
        if (rawItems.isEmpty() && scoreObj != null && scoreObj.has("notes") && scoreObj.get("notes").isJsonArray) {
            val notes = scoreObj.getAsJsonArray("notes")
            for (i in 0 until notes.size()) {
                val item = notes.get(i)
                if (!item.isJsonObject) continue
                val n = item.asJsonObject
                val timeMs = extractMgmTime(n)
                if (timeMs < 0L) continue
                val key = extractMgmKeyIndex(n)
                if (key in 0..14) {
                    rawItems.add(Pair(timeMs, key))
                }
            }
        }

        // 直接数组
        if (rawItems.isEmpty() && directNotesArray != null) {
            for (i in 0 until directNotesArray.size()) {
                val item = directNotesArray.get(i)
                if (!item.isJsonObject) continue
                val n = item.asJsonObject
                val timeMs = extractMgmTime(n)
                if (timeMs < 0L) continue
                val key = extractMgmKeyIndex(n)
                if (key in 0..14) {
                    rawItems.add(Pair(timeMs, key))
                }
            }
        }

        return buildSongWithMicroChords(rawItems, title, artist, bpm, "OnlineMGM")
    }

    private fun extractMgmTime(obj: JsonObject): Long {
        for (prop in arrayOf("startMs", "time", "timeMs", "start_ms", "start", "t", "timestamp")) {
            if (obj.has(prop) && !obj.get(prop).isJsonNull) {
                val prim = obj.get(prop).asJsonPrimitive
                if (prim.isNumber) return prim.asLong
                if (prim.isString) return prim.asString.trim().toLongOrNull() ?: -1L
            }
        }
        return -1L
    }

    /**
     * 音游伴侣官方乐谱键位提取：
     * 100% 确定按 targetKey ("sky.key.X") 或 keyIndex/pitch (1..15 -> X - 1) 解析
     */
    private fun extractMgmKeyIndex(obj: JsonObject): Int {
        // 1. targetKey: "sky.key.8" -> 7
        if (obj.has("targetKey") && !obj.get("targetKey").isJsonNull) {
            val s = obj.get("targetKey").asString.trim()
            val m = Regex("""key\.(\d+)""", RegexOption.IGNORE_CASE).find(s)
            if (m != null) {
                val num = m.groupValues[1].toIntOrNull()
                if (num != null && num in 1..15) return num - 1
            }
            val d = s.toIntOrNull()
            if (d != null && d in 1..15) return d - 1
        }

        // 2. keyIndex: 1..15 -> keyIndex - 1
        if (obj.has("keyIndex") && !obj.get("keyIndex").isJsonNull) {
            val n = obj.get("keyIndex").asString.trim().toIntOrNull()
            if (n != null && n in 1..15) return n - 1
        }

        // 3. pitch: 1..15 -> pitch - 1
        if (obj.has("pitch") && !obj.get("pitch").isJsonNull) {
            val n = obj.get("pitch").asString.trim().toIntOrNull()
            if (n != null && n in 1..15) return n - 1
        }

        // 4. rawKey: "1Key7" -> 7
        if (obj.has("rawKey") && !obj.get("rawKey").isJsonNull) {
            val s = obj.get("rawKey").asString.trim()
            val m = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(s)
            if (m != null) {
                val k = m.groupValues[1].toIntOrNull()
                if (k != null && k in 0..14) return k
            }
        }

        return -1
    }

    // ========================================================================
    // 通道 2: 社区标准 SkyStudio 规范解析器 (SKY_STUDIO)
    // ========================================================================
    private fun parseSkyStudioScore(
        scoreObj: JsonObject?,
        directNotesArray: JsonArray?,
        fallbackTitle: String,
        fallbackBpm: Int
    ): Song {
        var title = fallbackTitle
        var bpm = fallbackBpm
        var artist = "光遇玩家"

        val notesJsonArray = if (scoreObj != null && scoreObj.has("songNotes") && scoreObj.get("songNotes").isJsonArray) {
            scoreObj.getAsJsonArray("songNotes")
        } else directNotesArray

        if (scoreObj != null) {
            val t = getJsonString(scoreObj, "name", "title")
            if (t.isNotBlank()) title = t
            val a = getJsonString(scoreObj, "author", "artist")
            if (a.isNotBlank()) artist = a
            val b = getJsonInt(scoreObj, "bpm")
            if (b > 0) bpm = b
        }

        if (notesJsonArray == null || notesJsonArray.size() == 0) {
            Log.w(TAG, "[SkyStudio] songNotes array is empty for 《$title》")
            return Song(UUID.randomUUID().toString(), title, artist, bpm, emptyList(), 0L, type = "SkyStudio")
        }

        // 提取每个音符的原始数值
        data class SkyRaw(val rawTime: Double, val keyIndex: Int)
        val list = mutableListOf<SkyRaw>()

        for (i in 0 until notesJsonArray.size()) {
            val item = notesJsonArray.get(i)
            if (!item.isJsonObject) continue
            val obj = item.asJsonObject

            val timeVal = if (obj.has("time") && !obj.get("time").isJsonNull) {
                val prim = obj.get("time").asJsonPrimitive
                if (prim.isNumber) prim.asDouble else prim.asString.toDoubleOrNull() ?: -1.0
            } else -1.0

            if (timeVal < 0.0) continue

            val keyIndex = extractSkyStudioKey(obj)
            if (keyIndex in 0..14) {
                list.add(SkyRaw(timeVal, keyIndex))
            }
        }

        if (list.isEmpty()) {
            return Song(UUID.randomUUID().toString(), title, artist, bpm, emptyList(), 0L, type = "SkyStudio")
        }

        // SkyStudio 时间基准检查：
        // SkyStudio 官方保存的 time 原生就是绝对毫秒 (如 0, 125, 250, 500...)
        // 部分自制转换工具导出的 time 为 16 分音符槽位序号 (0, 1, 2, 3...)
        val maxTime = list.maxOf { it.rawTime }
        val isSlotIndex = list.size >= 8 && maxTime in 1.0..1200.0 && list.all { it.rawTime % 1.0 == 0.0 }
        val slotDurationMs = (60000.0 / bpm.coerceAtLeast(20)) / 4.0

        val rawItems = list.map {
            val finalMs = if (isSlotIndex) {
                Math.round(it.rawTime * slotDurationMs).toLong()
            } else {
                Math.round(it.rawTime).toLong()
            }
            Pair(finalMs.coerceAtLeast(0L), it.keyIndex)
        }

        return buildSongWithMicroChords(rawItems, title, artist, bpm, "SkyStudio")
    }

    /**
     * SkyStudio 官方键位规则：
     * "1Key0" ~ "1Key14", "2Key0" ~ "2Key14", 或纯数字 0..14
     * 100% 固定为 0-based！绝不减 1！
     */
    private fun extractSkyStudioKey(obj: JsonObject): Int {
        if (obj.has("key") && !obj.get("key").isJsonNull) {
            val s = obj.get("key").asString.trim()
            val m = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(s)
            if (m != null) {
                val k = m.groupValues[1].toIntOrNull()
                if (k != null && k in 0..14) return k
            }
            val d = s.toIntOrNull()
            if (d != null && d in 0..14) return d
        }
        return -1
    }

    // ========================================================================
    // 通道 3: 极简纯音符序列 / 通用自适应解析器 (GENERIC_RAW)
    // ========================================================================
    private fun parseGenericRawScore(
        scoreObj: JsonObject?,
        directNotesArray: JsonArray?,
        root: JsonElement,
        fallbackTitle: String,
        fallbackBpm: Int
    ): Song {
        var title = fallbackTitle
        var bpm = fallbackBpm
        var artist = "光遇玩家"

        if (scoreObj != null) {
            val t = getJsonString(scoreObj, "name", "title")
            if (t.isNotBlank()) title = t
            val a = getJsonString(scoreObj, "author", "artist")
            if (a.isNotBlank()) artist = a
            val b = getJsonInt(scoreObj, "bpm")
            if (b > 0) bpm = b
        }

        val noteObjects = mutableListOf<JsonObject>()
        if (directNotesArray != null) {
            for (i in 0 until directNotesArray.size()) {
                val it = directNotesArray.get(i)
                if (it.isJsonObject) noteObjects.add(it.asJsonObject)
            }
        } else {
            deepSearchRawNotes(root, noteObjects)
        }

        // 通用兜底提取
        val rawItems = mutableListOf<Pair<Long, Int>>()
        for (obj in noteObjects) {
            val timeMs = extractGenericTime(obj)
            if (timeMs < 0L) continue
            val key = extractGenericKey(obj)
            if (key in 0..14) {
                rawItems.add(Pair(timeMs, key))
            }
        }

        return buildSongWithMicroChords(rawItems, title, artist, bpm, "GenericJSON")
    }

    private fun extractGenericTime(obj: JsonObject): Long {
        for (prop in arrayOf("time", "startMs", "timeMs", "start", "t", "timestamp")) {
            if (obj.has(prop) && !obj.get(prop).isJsonNull) {
                val prim = obj.get(prop).asJsonPrimitive
                if (prim.isNumber) return prim.asLong
                if (prim.isString) return prim.asString.trim().toLongOrNull() ?: -1L
            }
        }
        return -1L
    }

    private fun extractGenericKey(obj: JsonObject): Int {
        for (prop in arrayOf("key", "rawKey", "targetKey", "pitch", "keyIndex")) {
            if (obj.has(prop) && !obj.get(prop).isJsonNull) {
                val s = obj.get(prop).asString.trim()

                // "1Key7" -> 7
                val m = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(s)
                if (m != null) {
                    val k = m.groupValues[1].toIntOrNull()
                    if (k != null && k in 0..14) return k
                }

                // "A1" ~ "C5"
                val tagMatch = Regex("""^([ABC])([1-5])$""", RegexOption.IGNORE_CASE).find(s)
                if (tagMatch != null) {
                    val row = when (tagMatch.groupValues[1].uppercase()) {
                        "A" -> 0
                        "B" -> 1
                        "C" -> 2
                        else -> 0
                    }
                    val col = (tagMatch.groupValues[2].toIntOrNull() ?: 1) - 1
                    return row * 5 + col
                }

                // "sky.key.8" -> 7
                val keyMatch = Regex("""key\.(\d+)""", RegexOption.IGNORE_CASE).find(s)
                if (keyMatch != null) {
                    val k = keyMatch.groupValues[1].toIntOrNull()
                    if (k != null && k in 1..15) return k - 1
                }

                val d = s.toIntOrNull()
                if (d != null) {
                    if (d in 0..14) return d
                    if (d in 1..15) return d - 1
                }
            }
        }
        return -1
    }

    // ========================================================================
    // 共享基础设施：微和弦智能聚合与歌曲构建 (消除手势队列堵塞)
    // ========================================================================
    private fun buildSongWithMicroChords(
        rawItems: List<Pair<Long, Int>>,
        title: String,
        artist: String,
        bpm: Int,
        type: String
    ): Song {
        if (rawItems.isEmpty()) {
            return Song(UUID.randomUUID().toString(), title, artist, bpm, emptyList(), 0L, type = type)
        }

        val sorted = rawItems.sortedWith(compareBy({ it.first }, { it.second }))
        val noteEvents = mutableListOf<NoteEvent>()
        var currentEventTime = -1L
        val currentKeys = mutableListOf<Int>()

        // 智能微和弦容差：<= 12ms 归并在同一打击帧，杜绝 Android 无障碍排队堵塞
        for ((timeMs, key) in sorted) {
            if (currentEventTime < 0L) {
                currentEventTime = timeMs
                currentKeys.add(key)
            } else if (timeMs - currentEventTime <= 12L) {
                if (!currentKeys.contains(key)) {
                    currentKeys.add(key)
                }
            } else {
                noteEvents.add(NoteEvent(timeMs = currentEventTime, keys = currentKeys.sorted()))
                currentEventTime = timeMs
                currentKeys.clear()
                currentKeys.add(key)
            }
        }
        if (currentKeys.isNotEmpty() && currentEventTime >= 0L) {
            noteEvents.add(NoteEvent(timeMs = currentEventTime, keys = currentKeys.sorted()))
        }

        noteEvents.sort()
        val durationMs = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L

        Log.i(TAG, "✅ [$type] 解析完成《$title》: 事件数=${noteEvents.size}, 总击键数=${noteEvents.sumOf { it.keys.size }}, BPM=$bpm, 时长=${durationMs}ms")

        return Song(
            id = UUID.randomUUID().toString(),
            title = title,
            artist = artist,
            bpm = bpm,
            notes = noteEvents,
            durationMs = durationMs,
            type = type
        )
    }

    private fun isPercussionTrack(trackObj: JsonObject): Boolean {
        val name = if (trackObj.has("name") && !trackObj.get("name").isJsonNull) {
            trackObj.get("name").asString.lowercase()
        } else ""

        val inst = if (trackObj.has("instrument") && !trackObj.get("instrument").isJsonNull) {
            trackObj.get("instrument").asString.lowercase()
        } else ""

        val combined = "$name $inst"
        return PERCUSSION_KEYWORDS.any { combined.contains(it) }
    }

    private fun deepSearchRawNotes(element: JsonElement, targetList: MutableList<JsonObject>) {
        if (element.isJsonObject) {
            val obj = element.asJsonObject
            if ((obj.has("time") || obj.has("startMs")) && (obj.has("key") || obj.has("targetKey") || obj.has("pitch") || obj.has("keyIndex") || obj.has("rawKey"))) {
                targetList.add(obj)
            } else {
                for ((_, v) in obj.entrySet()) {
                    deepSearchRawNotes(v, targetList)
                }
            }
        } else if (element.isJsonArray) {
            val arr = element.asJsonArray
            for (elem in arr) {
                deepSearchRawNotes(elem, targetList)
            }
        }
    }

    private fun getJsonString(obj: JsonObject, vararg keys: String): String {
        for (k in keys) {
            if (obj.has(k) && !obj.get(k).isJsonNull) {
                try {
                    val s = obj.get(k).asString.trim()
                    if (s.isNotBlank()) return s
                } catch (_: Exception) {}
            }
        }
        return ""
    }

    private fun getJsonInt(obj: JsonObject, vararg keys: String): Int {
        for (k in keys) {
            if (obj.has(k) && !obj.get(k).isJsonNull) {
                try {
                    val n = obj.get(k).asInt
                    if (n > 0) return n
                } catch (_: Exception) {
                    try {
                        val n = obj.get(k).asString.trim().toIntOrNull()
                        if (n != null && n > 0) return n
                    } catch (_: Exception) {}
                }
            }
        }
        return 0
    }
}
