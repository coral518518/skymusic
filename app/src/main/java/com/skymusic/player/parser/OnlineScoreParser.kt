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
 * 音游伴侣 (mgm.jie-you.cn) / 光遇乐谱专用直接解析器
 * 严格按照音游伴侣规范直接解析，杜绝任何复杂的二次音符转换或音高计算：
 * 1. notes: 弹奏点击 item 列表
 * 2. startMs: 触发时间戳 (毫秒)。相同 startMs 自动聚合为和弦同时按下
 * 3. 目标按键提取 (光遇 15 个键：1..15 对应内部 0..14 坐标索引)：
 *    - targetKey: 如 "sky.key.8" -> 第 8 键 -> 索引 7 (第二行第 3 键，高音 Do)
 *    - keyIndex: 如 8 -> 第 8 键 -> 索引 7
 *    - pitch: 如 8 -> 第 8 键 -> 索引 7
 *    - rawKey: 如 "1Key7" (SkyStudio 0 索引 7) -> 索引 7
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

        // 1. 解开外层包装 (如 { "success": true, "data": { "score": ... } })
        var current: JsonElement = rootElement
        if (current.isJsonPrimitive && current.asJsonPrimitive.isString) {
            try {
                current = JsonParser.parseString(current.asString)
            } catch (_: Exception) {}
        }

        // 提取元数据与定位核心 score/data 节点
        var targetObj: JsonObject? = if (current.isJsonObject) current.asJsonObject else null

        if (targetObj != null) {
            if (targetObj.has("data") && targetObj.get("data").isJsonObject) {
                targetObj = targetObj.getAsJsonObject("data")
            }
            if (targetObj.has("score") && targetObj.get("score").isJsonObject) {
                targetObj = targetObj.getAsJsonObject("score")
            }

            // 读取标题与 BPM
            if (targetObj.has("bpm") && !targetObj.get("bpm").isJsonNull) {
                val b = targetObj.get("bpm").asInt
                if (b > 0) bpm = b
            }
            if (targetObj.has("metadata") && targetObj.get("metadata").isJsonObject) {
                val meta = targetObj.getAsJsonObject("metadata")
                if (meta.has("title") && !meta.get("title").isJsonNull) title = meta.get("title").asString
                if (meta.has("artist") && !meta.get("artist").isJsonNull) artist = meta.get("artist").asString
                if (meta.has("bpm") && !meta.get("bpm").isJsonNull) {
                    val b = meta.get("bpm").asInt
                    if (b > 0) bpm = b
                }
            }
        }

        // 2. 核心提取：提取 tracks 声轨中的 notes 列表
        var notesFound = false
        if (targetObj != null && targetObj.has("tracks") && targetObj.get("tracks").isJsonArray) {
            val tracks = targetObj.getAsJsonArray("tracks")
            for (t in tracks) {
                if (!t.isJsonObject) continue
                val trackObj = t.asJsonObject
                // 忽略被静音的声轨
                if (trackObj.has("muted") && trackObj.get("muted").asBoolean) continue

                if (trackObj.has("notes") && trackObj.get("notes").isJsonArray) {
                    parseNotesArray(trackObj.getAsJsonArray("notes"), timeMap)
                    notesFound = true
                } else if (trackObj.has("songNotes") && trackObj.get("songNotes").isJsonArray) {
                    parseNotesArray(trackObj.getAsJsonArray("songNotes"), timeMap)
                    notesFound = true
                }
            }
        }

        // 若不是 tracks 结构，检查顶层 notes 或 songNotes
        if (!notesFound && targetObj != null) {
            if (targetObj.has("notes") && targetObj.get("notes").isJsonArray) {
                parseNotesArray(targetObj.getAsJsonArray("notes"), timeMap)
                notesFound = true
            } else if (targetObj.has("songNotes") && targetObj.get("songNotes").isJsonArray) {
                parseNotesArray(targetObj.getAsJsonArray("songNotes"), timeMap)
                notesFound = true
            }
        }

        // 兜底：如果是纯数组结构
        if (!notesFound) {
            if (rootElement.isJsonArray) {
                parseNotesArray(rootElement.asJsonArray, timeMap)
            } else {
                deepSearchNotes(rootElement, timeMap)
            }
        }

        // 3. 构造按时间递增的 NoteEvent 列表 (相同 startMs 自动合并为和弦)
        val noteEvents = mutableListOf<NoteEvent>()
        for ((timeMs, keys) in timeMap) {
            val sortedKeys = keys.filter { it in 0..14 }.sorted()
            if (sortedKeys.isNotEmpty()) {
                noteEvents.add(NoteEvent(timeMs = timeMs, keys = sortedKeys))
            }
        }
        noteEvents.sort()

        val durationMs = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L

        Log.i(TAG, "Parsed song《$title》: total note events = ${noteEvents.size}, total notes = ${noteEvents.sumOf { it.keys.size }}")

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

    /**
     * 遍历 notes 数组，将各个 note 按 startMs 归并
     */
    private fun parseNotesArray(notesArray: JsonArray, timeMap: MutableMap<Long, MutableSet<Int>>) {
        for (i in 0 until notesArray.size()) {
            val item = notesArray.get(i)
            if (!item.isJsonObject) continue
            val obj = item.asJsonObject

            // 1. 触发时间点 (startMs)
            val timeMs = extractTime(obj)
            if (timeMs < 0L) continue

            // 2. 目标按键索引 (0..14)
            val keyIndex = extractKeyIndex(obj)
            if (keyIndex in 0..14) {
                timeMap.getOrPut(timeMs) { mutableSetOf() }.add(keyIndex)
            }
        }
    }

    /**
     * 核心按键索引提取 (统一归一化为 0..14 内部坐标索引)：
     * 光遇键盘共 15 个按键 (1 ~ 15)：
     *   第 1 键 (A1 第一行第1键) -> 0
     *   第 8 键 (B3 第二行第3键，高音 Do) -> 7
     *   第 11 键 (C1 第三行第1键，高音 Fa) -> 10
     *   第 15 键 (C5 第三行第5键，倍高音 Do) -> 14
     */
    private fun extractKeyIndex(obj: JsonObject): Int {
        // A. 优先从 targetKey 读取 ("sky.key.8" -> 8, "8" -> 8)
        if (obj.has("targetKey") && !obj.get("targetKey").isJsonNull) {
            val key = parseOneBasedKey(obj.get("targetKey"))
            if (key in 0..14) return key
        }

        // B. 从 keyIndex 读取 (8 -> 8)
        if (obj.has("keyIndex") && !obj.get("keyIndex").isJsonNull) {
            val key = parseOneBasedKey(obj.get("keyIndex"))
            if (key in 0..14) return key
        }

        // C. 从 pitch 读取 (在音游伴侣中 pitch 即为 1..15 键位)
        if (obj.has("pitch") && !obj.get("pitch").isJsonNull) {
            val key = parseOneBasedKey(obj.get("pitch"))
            if (key in 0..14) return key
        }

        // D. 从 rawKey 读取 (如 "1Key7" -> 7, 或者 "8" -> 7)
        if (obj.has("rawKey") && !obj.get("rawKey").isJsonNull) {
            val elem = obj.get("rawKey")
            if (elem.isJsonPrimitive) {
                val str = elem.asString.trim()
                // SkyStudio 0-based 格式: "1Key0" ~ "1Key14"
                val matchKey = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(str)
                if (matchKey != null) {
                    val k = matchKey.groupValues[1].toIntOrNull()
                    if (k != null && k in 0..14) return k
                }
                // 纯数字 "1"~"15"
                val direct = str.toIntOrNull()
                if (direct != null && direct in 1..15) {
                    return direct - 1
                }
            }
        }

        // E. 传统 SkyStudio "key" 字段 ("1Key7" -> 7)
        if (obj.has("key") && !obj.get("key").isJsonNull) {
            val elem = obj.get("key")
            if (elem.isJsonPrimitive) {
                val str = elem.asString.trim()
                val matchKey = Regex(""".*Key(\d+)""", RegexOption.IGNORE_CASE).find(str)
                if (matchKey != null) {
                    val k = matchKey.groupValues[1].toIntOrNull()
                    if (k != null && k in 0..14) return k
                }
                val direct = str.toIntOrNull()
                if (direct != null && direct in 1..15) {
                    return direct - 1
                }
            }
        }

        return -1
    }

    /**
     * 将 1-based 按键标示 (1..15) 映射为内部 0..14 坐标索引
     */
    private fun parseOneBasedKey(elem: JsonElement): Int {
        if (!elem.isJsonPrimitive) return -1
        val prim = elem.asJsonPrimitive
        if (prim.isNumber) {
            val n = prim.asInt
            if (n in 1..15) return n - 1
        } else if (prim.isString) {
            val str = prim.asString.trim()
            // 匹配 "sky.key.8" 或 "key.8"
            val match = Regex("""key\.(\d+)""", RegexOption.IGNORE_CASE).find(str)
            if (match != null) {
                val n = match.groupValues[1].toIntOrNull()
                if (n != null && n in 1..15) return n - 1
            }
            // 纯数字 "8"
            val direct = str.toIntOrNull()
            if (direct != null && direct in 1..15) {
                return direct - 1
            }
        }
        return -1
    }

    /**
     * 提取触发时间戳 (毫秒)
     */
    private fun extractTime(obj: JsonObject): Long {
        for (timeProp in arrayOf("startMs", "time", "timeMs", "start_ms", "start", "t", "timestamp")) {
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

    /**
     * 兜底递归全树搜索
     */
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
                } else {
                    for (elem in arr) {
                        deepSearchNotes(elem, timeMap)
                    }
                }
            }
        }
    }
}
