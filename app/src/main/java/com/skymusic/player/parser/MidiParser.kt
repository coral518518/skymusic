package com.skymusic.player.parser

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.Charset
import java.util.UUID
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.roundToLong
import kotlin.math.sqrt

/**
 * MIDI -> 光遇 15 键高保真转换解析器 (移植自 demo.py V7)
 *
 * 核心特性：
 * 1. 自动抽取音轨音符并智能评估单线条旋律性（排除伴奏琶音与打击乐）
 * 2. 乐句动态切分与二阶动态规划 (2nd-order DP) 寻找最连贯主旋律线
 * 3. Krumhansl-Schmuckler 调性概率识别与二次调性精修 (Major/Minor)
 * 4. 12 半音白键空间最优归一化转调与全局音程保真 DP 映射 (杜绝乱八度折叠)
 * 5. 自适应节奏网格量化与单音防粘音处理
 * 6. 强拍稀疏伴奏低音抽取与旋律优先合成
 * 7. 导入中文文件名强保障（导入什么名字即显示什么名字）
 */
object MidiParser {

    data class RawNote(
        val pitch: Int,
        val start: Long,
        val dur: Long,
        val track: Int,
        val channel: Int,
        val velocity: Int,
        var melodyProb: Double = 0.5
    )

    data class TempoChange(
        val tick: Long,
        val usPerQuarter: Long
    )

    data class MelodyEvent(
        val key: Int,
        val pitch: Int,
        val originalPitch: Int,
        val start: Long,
        val end: Long,
        val dur: Long,
        val velocity: Int,
        val isMelody: Boolean
    )

    private data class ActiveNote(
        val start: Long,
        val velocity: Int
    )

    // 光遇 15 键对应的绝对 MIDI 音高 (C3 ~ C5)
    val SKY_KEYS_MIDI = intArrayOf(
        48, 50, 52, 53, 55, 57, 59, // A1 ~ A5, B1 ~ B2 (C3 ~ B3)
        60, 62, 64, 65, 67, 69, 71, // B3 ~ B5, C1 ~ C4 (C4 ~ B4)
        72                          // C5 (C5)
    )

    val SKY_PITCH_MAP = SKY_KEYS_MIDI
    val SKY_KEY_PITCHES = SKY_KEYS_MIDI

    val SKY_KEY_TAGS = arrayOf(
        "A1", "A2", "A3", "A4", "A5",
        "B1", "B2", "B3", "B4", "B5",
        "C1", "C2", "C3", "C4", "C5"
    )

    val NOTE_NAMES = arrayOf(
        "C", "C#", "D", "D#", "E", "F",
        "F#", "G", "G#", "A", "A#", "B"
    )

    val WHITE_PITCH_CLASSES = setOf(0, 2, 4, 5, 7, 9, 11)

    val MAJOR_SCALE = intArrayOf(0, 2, 4, 5, 7, 9, 11)
    val MINOR_SCALE = intArrayOf(0, 2, 3, 5, 7, 8, 10)
    val MAJOR_STEPS = MAJOR_SCALE

    // Krumhansl-Kessler 调性先验 Profile
    val MAJOR_PROFILE = doubleArrayOf(
        6.35, 2.23, 3.48, 2.33,
        4.38, 4.09, 2.52, 5.19,
        2.39, 3.66, 2.29, 2.88
    )

    val MINOR_PROFILE = doubleArrayOf(
        6.33, 2.68, 3.52, 5.38,
        2.60, 3.53, 2.54, 4.75,
        3.98, 2.69, 3.34, 3.17
    )

    // ============================================================
    // 通用数学与音理工具
    // ============================================================

    fun clamp(value: Double, low: Double, high: Double): Double = max(low, min(high, value))

    fun pearson(a: DoubleArray, b: DoubleArray): Double {
        if (a.size != b.size || a.isEmpty()) return 0.0
        val ma = a.average()
        val mb = b.average()
        var numerator = 0.0
        var da = 0.0
        var db = 0.0
        for (i in a.indices) {
            val xa = a[i] - ma
            val xb = b[i] - mb
            numerator += xa * xb
            da += xa * xa
            db += xb * xb
        }
        val denominator = sqrt(da * db)
        return if (denominator == 0.0) 0.0 else numerator / denominator
    }

    fun snapGrid(value: Long, grid: Long): Long {
        return Math.rint(value.toDouble() / grid).toLong() * grid
    }

    fun pitchClassDistance(a: Int, b: Int): Int {
        val d = abs(((a % 12) + 12) % 12 - ((b % 12) + 12) % 12)
        return min(d, 12 - d)
    }

    // ============================================================
    // 核心对外接口
    // ============================================================

    /**
     * 解析标准 MIDI 并转换为光遇 15 键乐谱
     * @param defaultTitle 用户导入的文件名或默认曲名。若有效传入，将强制保持不变，避免被 MIDI 英文音轨名篡改。
     */
    fun parse(inputStream: InputStream, defaultTitle: String = "MIDI 乐谱"): Song {
        val bytes = inputStream.readBytes()
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)

        // 1. 读取 Header 块
        val headerId = ByteArray(4)
        buffer.get(headerId)
        if (String(headerId) != "MThd") {
            throw IllegalArgumentException("非标准 MIDI 文件格式 (缺少 MThd 标识)")
        }

        val headerSize = buffer.int
        buffer.short // format
        val numTracks = buffer.short.toInt()
        val division = buffer.short.toInt() // PPQ
        val ppq = if (division > 0) division else 480

        if (headerSize > 6) {
            buffer.position(buffer.position() + (headerSize - 6))
        }

        val rawTempoChanges = mutableListOf<TempoChange>()

        // 规范化初始曲名
        var songTitle = defaultTitle.trim()
        val hasExplicitTitle = songTitle.isNotEmpty() &&
                songTitle != "MIDI 乐谱" &&
                songTitle != "未命名乐谱" &&
                songTitle != "导入乐谱"

        val tracks = mutableListOf<List<RawNote>>()

        // 2. 逐音轨提取音符 (排除 Channel 9 打击乐)
        for (t in 0 until numTracks) {
            if (buffer.remaining() < 8) break
            val trackId = ByteArray(4)
            buffer.get(trackId)
            val trackLength = buffer.int
            val trackEndPos = buffer.position() + trackLength

            var currentTick = 0L
            var runningStatus = 0
            val activeNotes = mutableMapOf<Pair<Int, Int>, ActiveNote>()
            val trackNotes = mutableListOf<RawNote>()

            while (buffer.position() < trackEndPos && buffer.hasRemaining()) {
                val delta = readVariableLength(buffer)
                currentTick += delta

                if (!buffer.hasRemaining()) break
                var status = buffer.get().toInt() and 0xFF

                if (status < 0x80) {
                    if (runningStatus == 0) break
                    status = runningStatus
                    buffer.position(buffer.position() - 1)
                } else {
                    runningStatus = if (status < 0xF0) status else 0
                }

                if (status == 0xFF) {
                    // Meta 事件
                    if (!buffer.hasRemaining()) break
                    val metaType = buffer.get().toInt() and 0xFF
                    val metaLen = readVariableLength(buffer).toInt()
                    val metaData = ByteArray(metaLen)
                    if (buffer.remaining() >= metaLen) {
                        buffer.get(metaData)
                    } else {
                        buffer.position(buffer.limit())
                        break
                    }

                    when (metaType) {
                        0x03 -> { // Track Name / Title
                            // 仅当用户未指定具体文件名时，才从音轨名称提取
                            if (!hasExplicitTitle && (songTitle.isBlank() || songTitle == "MIDI 乐谱" || songTitle == "未命名乐谱")) {
                                val name = decodeMidiText(metaData).trim()
                                if (name.isNotEmpty()) {
                                    songTitle = name
                                }
                            }
                        }
                        0x51 -> { // Set Tempo
                            if (metaLen >= 3) {
                                val us = ((metaData[0].toInt() and 0xFF) shl 16) or
                                        ((metaData[1].toInt() and 0xFF) shl 8) or
                                        (metaData[2].toInt() and 0xFF)
                                rawTempoChanges.add(TempoChange(currentTick, us.toLong()))
                            }
                        }
                    }
                } else if (status == 0xF0 || status == 0xF7) {
                    val sysexLen = readVariableLength(buffer).toInt()
                    if (buffer.remaining() >= sysexLen) {
                        buffer.position(buffer.position() + sysexLen)
                    } else {
                        buffer.position(buffer.limit())
                    }
                } else {
                    val msgType = status and 0xF0
                    val channel = status and 0x0F
                    when (msgType) {
                        0x90 -> { // Note On
                            if (buffer.remaining() >= 2) {
                                val note = buffer.get().toInt() and 0xFF
                                val vel = buffer.get().toInt() and 0xFF
                                if (channel != 9) { // 忽略鼓声轨
                                    val key = Pair(channel, note)
                                    if (vel > 0) {
                                        val old = activeNotes.remove(key)
                                        if (old != null && currentTick > old.start) {
                                            trackNotes.add(
                                                RawNote(note, old.start, currentTick - old.start, t, channel, old.velocity)
                                            )
                                        }
                                        activeNotes[key] = ActiveNote(currentTick, vel)
                                    } else {
                                        val old = activeNotes.remove(key)
                                        if (old != null) {
                                            val dur = currentTick - old.start
                                            if (dur > 0) {
                                                trackNotes.add(
                                                    RawNote(note, old.start, dur, t, channel, old.velocity)
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        0x80 -> { // Note Off
                            if (buffer.remaining() >= 2) {
                                val note = buffer.get().toInt() and 0xFF
                                buffer.get() // vel
                                if (channel != 9) {
                                    val key = Pair(channel, note)
                                    val old = activeNotes.remove(key)
                                    if (old != null) {
                                        val dur = currentTick - old.start
                                        if (dur > 0) {
                                            trackNotes.add(
                                                RawNote(note, old.start, dur, t, channel, old.velocity)
                                            )
                                        }
                                    }
                                }
                            }
                        }
                        0xA0, 0xB0, 0xE0 -> {
                            if (buffer.remaining() >= 2) {
                                buffer.get()
                                buffer.get()
                            }
                        }
                        0xC0, 0xD0 -> {
                            if (buffer.hasRemaining()) {
                                buffer.get()
                            }
                        }
                    }
                }
            }

            // 处理没有显式 note_off 的尾部悬挂音符
            val fallbackDur = max(ppq / 4L, 1L)
            for ((key, old) in activeNotes) {
                val duration = max(fallbackDur, currentTick - old.start)
                trackNotes.add(RawNote(key.second, old.start, duration, t, key.first, old.velocity))
            }

            if (trackNotes.isNotEmpty()) {
                trackNotes.sortWith(compareBy<RawNote> { it.start }.thenBy { it.pitch })
                tracks.add(trackNotes)
            }

            buffer.position(trackEndPos.coerceAtMost(buffer.limit()))
        }

        if (tracks.isEmpty()) {
            return Song(
                id = UUID.randomUUID().toString(),
                title = songTitle.ifBlank { "空 MIDI 乐谱" },
                artist = "未知",
                bpm = 120,
                notes = emptyList(),
                durationMs = 0L,
                type = "MIDI"
            )
        }

        val allNotes = tracks.flatten()

        // 解析并统一节拍与速度映射
        val tempoChanges = mutableListOf<TempoChange>()
        if (rawTempoChanges.isEmpty()) {
            tempoChanges.add(TempoChange(0L, 500_000L))
        } else {
            rawTempoChanges.sortBy { it.tick }
            val byTick = mutableMapOf<Long, Long>()
            for (tc in rawTempoChanges) {
                byTick[tc.tick] = tc.usPerQuarter
            }
            for ((tick, us) in byTick.toSortedMap()) {
                tempoChanges.add(TempoChange(tick, us))
            }
            if (tempoChanges.first().tick > 0L) {
                tempoChanges.add(0, TempoChange(0L, tempoChanges.first().usPerQuarter))
            }
        }

        val initialTempoUs = if (tempoChanges.first().tick == 0L && tempoChanges.first().usPerQuarter != 500_000L) {
            tempoChanges.first().usPerQuarter
        } else if (tempoChanges.size > 1) {
            tempoChanges[1].usPerQuarter
        } else {
            tempoChanges.first().usPerQuarter
        }
        val bpm = (60_000_000.0 / initialTempoUs).roundToInt().coerceIn(30, 300)

        // 智能直通识别：如果传入的 MIDI 所有音符都已经在光遇 15 键 (48..72 白键) 范围内，
        // 说明这已经是经过 demo.py 转换完成的 15 键成品试听 MIDI (如 sky_preview_v7.mid)，直接直通载入，无需二次分析
        val isAlreadySkyMidi = allNotes.isNotEmpty() && allNotes.all { it.pitch in SKY_KEYS_MIDI }
        if (isAlreadySkyMidi) {
            val timeMap = mutableMapOf<Long, MutableList<Int>>()
            for (note in allNotes) {
                val timeMs = tickToMillis(note.start, ppq, tempoChanges)
                val key = SKY_KEYS_MIDI.indexOf(note.pitch)
                if (key in 0..14) {
                    timeMap.getOrPut(timeMs) { mutableListOf() }.add(key)
                }
            }
            val noteEvents = mutableListOf<NoteEvent>()
            for ((timeMs, rawKeys) in timeMap) {
                noteEvents.add(NoteEvent(timeMs = timeMs, keys = rawKeys.distinct().sorted()))
            }
            noteEvents.sort()
            val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L
            return Song(
                id = UUID.randomUUID().toString(),
                title = songTitle,
                artist = "15键成品直通",
                bpm = bpm,
                notes = noteEvents,
                durationMs = duration,
                type = "MIDI"
            )
        }

        // 3. 旋律候选池筛选与分离伴奏轨
        val (melodyCandidates, accompaniment) = selectMelody(tracks, ppq)
        if (melodyCandidates.isEmpty()) {
            return Song(
                id = UUID.randomUUID().toString(),
                title = songTitle,
                artist = "未能识别旋律",
                bpm = 120,
                notes = emptyList(),
                durationMs = 0L,
                type = "MIDI"
            )
        }

        // 4. 第一遍：无调性约束寻找连贯旋律线
        var melody = cleanMelody(melodyCandidates, ppq)
        if (melody.isEmpty()) {
            melody = melodyCandidates
        }

        // 5. 第一次调性检测 (Krumhansl-Schmuckler 算法)
        var (tonic, mode, keyDesc) = detectKey(melody, allNotes)

        // 6. 第二遍：以调性为软约束进行二次精修，减少误选和声内声部
        val refinedMelody = refineMelodyWithKey(melodyCandidates, melody, tonic, mode, ppq)
        if (refinedMelody.size >= max(1, (melody.size * 0.72).toInt())) {
            melody = refinedMelody
        }

        // 再次复核调性
        val keyRecheck = detectKey(melody, allNotes)
        tonic = keyRecheck.first
        mode = keyRecheck.second
        keyDesc = keyRecheck.third

        // 7. 12 半音全域搜索最契合白键空间的归一化转调
        val normalizationShift = chooseNormalizationShift(melody, tonic, mode)

        // 8. 八度自适应模拟搜索 (基于 DP 序列映射成本评估)
        val octaveShift = chooseBestOctaveShift(melody, normalizationShift)

        // 9. 构建光遇 15 键旋律事件与自适应网格
        val (melodyEvents, grid) = buildMelodyEvents(
            melody,
            normalizationShift,
            octaveShift,
            ppq
        )

        // 10. 抽取稀疏强拍伴奏低音
        val bassEvents = buildBassEvents(
            accompaniment,
            normalizationShift,
            octaveShift,
            ppq,
            melodyEvents,
            grid
        )

        // 11. 合并旋律与伴奏
        val finalEvents = mergeEvents(melodyEvents, bassEvents)

        // 12. 转换成 Android NoteEvent 时间戳事件集合
        val timeMap = mutableMapOf<Long, MutableList<Int>>()

        for (event in finalEvents) {
            val timeMs = tickToMillis(event.start, ppq, tempoChanges)
            timeMap.getOrPut(timeMs) { mutableListOf() }.add(event.key)
        }

        val noteEvents = mutableListOf<NoteEvent>()
        for ((timeMs, rawKeys) in timeMap) {
            val distinctKeys = rawKeys.distinct().sorted()
            noteEvents.add(NoteEvent(timeMs = timeMs, keys = distinctKeys))
        }
        noteEvents.sort()

        val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L

        return Song(
            id = UUID.randomUUID().toString(),
            title = songTitle,
            artist = "$keyDesc (转调 $normalizationShift, 八度 $octaveShift)",
            bpm = bpm,
            notes = noteEvents,
            durationMs = duration,
            type = "MIDI"
        )
    }

    // ============================================================
    // 音轨旋律性评分与候选池混合
    // ============================================================

    fun scoreTrack(notes: List<RawNote>, ticksPerBeat: Int): Double {
        if (notes.isEmpty()) return -999999.0

        val ordered = notes.sortedWith(compareBy<RawNote> { it.start }.thenBy { it.pitch })
        val starts = ordered.map { it.start }
        val pitches = ordered.map { it.pitch }
        val durations = ordered.map { it.dur }

        val onsetGroups = ordered.groupBy { it.start }
        val polyphonicOnsets = onsetGroups.values.count { it.size > 1 }
        val onsetCount = onsetGroups.size
        val polyphonyRate = polyphonicOnsets.toDouble() / max(1, onsetCount)

        val avgPitch = pitches.average()
        val pitchRange = (pitches.maxOrNull() ?: 0) - (pitches.minOrNull() ?: 0)

        val onsetPitch = mutableListOf<RawNote>()
        for (start in onsetGroups.keys.sorted()) {
            val group = onsetGroups[start]!!
            val best = group.maxWithOrNull(
                compareBy<RawNote> { it.dur }.thenBy { it.velocity }.thenBy { it.pitch }
            )!!
            onsetPitch.add(best)
        }

        val intervals = mutableListOf<Int>()
        for (idx in 0 until onsetPitch.size - 1) {
            intervals.add(abs(onsetPitch[idx + 1].pitch - onsetPitch[idx].pitch))
        }

        val avgInterval: Double
        val smallMotionRate: Double
        val hugeLeapRate: Double
        if (intervals.isNotEmpty()) {
            avgInterval = intervals.average()
            smallMotionRate = intervals.count { it <= 7 }.toDouble() / intervals.size
            hugeLeapRate = intervals.count { it >= 12 }.toDouble() / intervals.size
        } else {
            avgInterval = 0.0
            smallMotionRate = 1.0
            hugeLeapRate = 0.0
        }

        val shortRate = durations.count { it <= ticksPerBeat / 2 }.toDouble() / durations.size
        val density = notes.size.toDouble() / max(1, starts.toSet().size)
        val densityScore = clamp(notes.size / 220.0, 0.0, 1.0)
        val pitchCenterScore = clamp(1.0 - abs(avgPitch - 69.0) / 35.0, 0.0, 1.0)
        val rangeScore = clamp(pitchRange / 30.0, 0.0, 1.0)

        val contourScore = smallMotionRate * 28.0 - hugeLeapRate * 20.0 + clamp(avgInterval / 8.0, 0.0, 1.0) * 8.0

        return densityScore * 18.0 +
                pitchCenterScore * 10.0 +
                rangeScore * 18.0 +
                (1.0 - polyphonyRate) * 42.0 +
                shortRate * 6.0 +
                contourScore -
                max(0.0, density - 3.0) * 4.0
    }

    private fun trackMelodyProbability(notes: List<RawNote>, ticksPerBeat: Int): Map<RawNote, Double> {
        if (notes.isEmpty()) return emptyMap()

        val groups = notes.groupBy { it.start }
        val pitches = notes.map { it.pitch }.sorted()
        val center = if (pitches.size % 2 == 1) {
            pitches[pitches.size / 2].toDouble()
        } else {
            (pitches[pitches.size / 2 - 1] + pitches[pitches.size / 2]) / 2.0
        }
        val spread = max(12.0, (pitches.last() - pitches.first()) * 0.55)

        val result = mutableMapOf<RawNote, Double>()
        for (n in notes) {
            val onsetGroup = groups[n.start]!!
            val chordSize = onsetGroup.size
            val pitchPref = 1.0 - min(1.0, abs(n.pitch - center) / spread)
            val durationPref = min(1.0, n.dur.toDouble() / max(1, ticksPerBeat))
            val velocityPref = n.velocity / 127.0

            val chordPenalty = 1.0 / (1.0 + max(0, chordSize - 1) * 0.28)
            val score = (
                    0.32 * pitchPref +
                            0.32 * durationPref +
                            0.16 * velocityPref +
                            0.20
                    ) * chordPenalty
            result[n] = score
        }
        return result
    }

    fun selectMelody(tracks: List<List<RawNote>>, ticksPerBeat: Int): Pair<List<RawNote>, List<RawNote>> {
        if (tracks.isEmpty()) return Pair(emptyList(), emptyList())
        if (tracks.size == 1) return Pair(tracks[0], emptyList())

        val scored = tracks.mapIndexed { idx, notes ->
            Triple(scoreTrack(notes, ticksPerBeat), idx, notes)
        }.sortedByDescending { it.first }

        val topTrackCount = 3
        val selected = scored.take(min(topTrackCount, scored.size))

        val candidates = mutableListOf<RawNote>()
        for ((rank, item) in selected.withIndex()) {
            val notes = item.third
            val probMap = trackMelodyProbability(notes, ticksPerBeat)
            val trackFactor = 1.0 / (1.0 + rank * 0.18)
            for (n in notes) {
                val prob = (probMap[n] ?: 0.5) * trackFactor
                candidates.add(n.copy(melodyProb = prob))
            }
        }

        // 同 onset + 同 pitch 去重
        val grouped = candidates.groupBy { Pair(it.start, it.pitch) }
        val dedup = mutableListOf<RawNote>()
        for (group in grouped.values) {
            val best = group.maxWithOrNull(
                compareBy<RawNote> { it.melodyProb }
                    .thenBy { it.dur }
                    .thenBy { it.velocity }
            )!!
            dedup.add(best)
        }

        dedup.sortWith(compareBy<RawNote> { it.start }.thenBy { it.pitch })

        val minDur = max(1L, (ticksPerBeat / 48).toLong())
        val cleanedPool = dedup.filter { it.dur >= minDur }

        val selectedIndices = selected.map { it.second }.toSet()
        val accompaniment = mutableListOf<RawNote>()
        for (trackIndex in tracks.indices) {
            if (trackIndex in selectedIndices) continue
            accompaniment.addAll(tracks[trackIndex])
        }

        return Pair(cleanedPool, accompaniment)
    }

    // ============================================================
    // 乐句切分与二阶动态规划主旋律提取
    // ============================================================

    private fun phraseSegments(notes: List<RawNote>, ticksPerBeat: Int): List<List<RawNote>> {
        if (notes.isEmpty()) return emptyList()

        val ordered = notes.sortedWith(compareBy<RawNote> { it.start }.thenBy { it.pitch })
        val gapThreshold = max((ticksPerBeat * 0.85).toLong(), 1L)

        val segments = mutableListOf<MutableList<RawNote>>()
        var current = mutableListOf(ordered[0])

        for (i in 0 until ordered.size - 1) {
            val prev = ordered[i]
            val cur = ordered[i + 1]
            val gap = cur.start - (prev.start + prev.dur)
            if (gap >= gapThreshold) {
                segments.add(current)
                current = mutableListOf(cur)
            } else {
                current.add(cur)
            }
        }
        if (current.isNotEmpty()) {
            segments.add(current)
        }
        return segments
    }

    private fun buildOnsetGroups(notes: List<RawNote>, ticksPerBeat: Int): List<Pair<Long, List<RawNote>>> {
        val minDuration = max(1L, (ticksPerBeat / 48).toLong())
        val groups = notes.filter { it.dur >= minDuration }.groupBy { it.start }

        val result = mutableListOf<Pair<Long, List<RawNote>>>()
        for (start in groups.keys.sorted()) {
            val group = groups[start]!!
            val bestByPitch = mutableMapOf<Int, RawNote>()
            for (note in group) {
                val old = bestByPitch[note.pitch]
                if (old == null ||
                    (note.melodyProb > old.melodyProb) ||
                    (note.melodyProb == old.melodyProb && note.dur > old.dur) ||
                    (note.melodyProb == old.melodyProb && note.dur == old.dur && note.velocity > old.velocity)
                ) {
                    bestByPitch[note.pitch] = note
                }
            }

            val dedup = bestByPitch.values.toMutableList()
            dedup.sortWith { a, b ->
                val c1 = b.melodyProb.compareTo(a.melodyProb)
                if (c1 != 0) return@sortWith c1
                val durA = min(a.dur, ticksPerBeat.toLong() * 2)
                val durB = min(b.dur, ticksPerBeat.toLong() * 2)
                val c2 = durB.compareTo(durA)
                if (c2 != 0) return@sortWith c2
                val c3 = b.velocity.compareTo(a.velocity)
                if (c3 != 0) return@sortWith c3
                b.pitch.compareTo(a.pitch)
            }

            result.add(Pair(start, dedup.take(8)))
        }
        return result
    }

    private fun scaleCost(note: RawNote, tonic: Int, mode: String, phraseEnd: Boolean): Double {
        val scale = if (mode == "major") MAJOR_SCALE else MINOR_SCALE
        val rel = ((note.pitch - tonic) % 12 + 12) % 12

        if (rel in scale) {
            var cost = -0.55
            if (phraseEnd && (rel == 0 || rel == 7)) {
                cost -= 1.0
            }
            return cost
        }

        var nearest = 12
        for (x in scale) {
            val d = pitchClassDistance(rel, x)
            if (d < nearest) nearest = d
        }
        return 0.65 + nearest * 0.55
    }

    private fun transitionCostForMelody(prevNote: RawNote, note: RawNote, ticksPerBeat: Int): Double {
        val interval = note.pitch - prevNote.pitch
        val a = abs(interval)
        var cost = when {
            a == 0 -> -1.8
            a <= 2 -> -2.7
            a <= 4 -> -2.1
            a <= 7 -> -0.7
            a <= 9 -> 0.3
            a <= 11 -> 1.2
            else -> 3.0 + (a - 12) * 0.35
        }

        if (a >= 19) cost += 4.0
        if (prevNote.dur >= ticksPerBeat * 1.5 && a >= 10) cost += 1.8

        return cost
    }

    private fun secondOrderTransition(prev2: RawNote?, prev1: RawNote?, cur: RawNote): Double {
        if (prev2 == null || prev1 == null) return 0.0

        val d1 = prev1.pitch - prev2.pitch
        val d2 = cur.pitch - prev1.pitch
        var cost = 0.0

        if (abs(d1) >= 7 && (d1.toLong() * d2.toLong() < 0)) cost -= 1.0
        if (abs(d1) >= 9 && abs(d2) >= 9 && (d1.toLong() * d2.toLong() > 0)) cost += 2.4
        if (d1 == 0 && d2 == 0) cost -= 0.8

        return cost
    }

    private fun rhythmSignature(segment: List<RawNote>): List<Int> {
        val starts = segment.map { it.start }
        if (starts.size < 2) return emptyList()
        val gaps = starts.zipWithNext { a, b -> max(1L, b - a) }
        val sortedGaps = gaps.sorted()
        val base = if (sortedGaps.size % 2 == 1) {
            sortedGaps[sortedGaps.size / 2].toDouble()
        } else {
            (sortedGaps[sortedGaps.size / 2 - 1] + sortedGaps[sortedGaps.size / 2]) / 2.0
        }
        if (base <= 0.0) return emptyList()
        return gaps.map { clamp((it.toDouble() / base).roundToInt().toDouble(), 1.0, 6.0).toInt() }
    }

    private fun phraseSimilarity(a: List<RawNote>, b: List<RawNote>): Double {
        if (a.isEmpty() || b.isEmpty()) return 0.0
        val lengthScore = 1.0 - min(abs(a.size - b.size), 6) / 6.0
        val sa = rhythmSignature(a)
        val sb = rhythmSignature(b)
        val rhythmScore = if (sa.isEmpty() || sb.isEmpty()) {
            0.5
        } else {
            val m = min(sa.size, sb.size)
            var matches = 0
            for (i in 0 until m) {
                if (sa[i] == sb[i]) matches++
            }
            matches.toDouble() / max(sa.size, sb.size)
        }
        return lengthScore * 0.55 + rhythmScore * 0.45
    }

    private fun choosePhrasePath(
        candidates: List<Pair<Long, List<RawNote>>>,
        ticksPerBeat: Int,
        tonic: Int? = null,
        mode: String = "major",
        motifReference: List<RawNote>? = null
    ): List<RawNote> {
        if (candidates.isEmpty()) return emptyList()
        if (candidates.size == 1) return if (candidates[0].second.isNotEmpty()) listOf(candidates[0].second[0]) else emptyList()

        val first = candidates[0].second
        val second = candidates[1].second
        if (first.isEmpty() || second.isEmpty()) return emptyList()

        var states = mutableMapOf<Pair<Int, Int>, Double>()
        val backLayers = mutableListOf<MutableMap<Pair<Int, Int>, Pair<Int, Int>>?>()
        backLayers.add(null)
        backLayers.add(mutableMapOf())

        val ref = motifReference ?: emptyList()

        fun localCost(note: RawNote, pos: Int, phraseLen: Int): Double {
            var cost = -note.melodyProb * 4.6 -
                    min(note.dur.toDouble() / max(1, ticksPerBeat), 2.5) * 0.65 +
                    abs(note.pitch - 69) * 0.028
            if (tonic != null) {
                cost += scaleCost(note, tonic, mode, phraseEnd = (pos == phraseLen - 1))
            }
            return cost
        }

        for (i in first.indices) {
            val ca = localCost(first[i], 0, candidates.size)
            for (j in second.indices) {
                val cb = localCost(second[j], 1, candidates.size)
                var cost = ca + cb + transitionCostForMelody(first[i], second[j], ticksPerBeat)
                if (ref.size == candidates.size) {
                    val refInt = ref[1].pitch - ref[0].pitch
                    val curInt = second[j].pitch - first[i].pitch
                    if ((refInt > 0) != (curInt > 0) && refInt != 0 && curInt != 0) {
                        cost += 1.15
                    }
                    cost += abs(abs(curInt) - abs(refInt)) * 0.10
                }
                states[Pair(i, j)] = cost
                backLayers[1]!![Pair(i, j)] = Pair(-1, -1)
            }
        }

        for (pos in 2 until candidates.size) {
            val group = candidates[pos].second
            val prevGroup = candidates[pos - 1].second
            val prev2Group = candidates[pos - 2].second
            val nextStates = mutableMapOf<Pair<Int, Int>, Double>()
            val nextBack = mutableMapOf<Pair<Int, Int>, Pair<Int, Int>>()

            for ((state, prevCost) in states) {
                val i2 = state.first
                val i1 = state.second
                if (i2 >= prev2Group.size || i1 >= prevGroup.size) continue
                val prev2 = prev2Group[i2]
                val prev1 = prevGroup[i1]

                for (ci in group.indices) {
                    val cur = group[ci]
                    var cost = prevCost + localCost(cur, pos, candidates.size)
                    cost += transitionCostForMelody(prev1, cur, ticksPerBeat)
                    cost += secondOrderTransition(prev2, prev1, cur)

                    if (ref.size == candidates.size && pos < ref.size) {
                        val refD = ref[pos].pitch - ref[pos - 1].pitch
                        val curD = cur.pitch - prev1.pitch
                        if (refD != 0 && curD != 0 && (refD > 0) != (curD > 0)) {
                            cost += 1.15
                        }
                        cost += abs(abs(curD) - abs(refD)) * 0.10
                    }

                    val stateKey = Pair(i1, ci)
                    val oldCost = nextStates[stateKey] ?: Double.POSITIVE_INFINITY
                    if (cost < oldCost) {
                        nextStates[stateKey] = cost
                        nextBack[stateKey] = Pair(i2, i1)
                    }
                }
            }

            states = nextStates
            backLayers.add(nextBack)
            if (states.isEmpty()) return emptyList()
        }

        val bestEntry = states.minByOrNull { it.value } ?: return emptyList()
        val bestState = bestEntry.key
        val chosenIndices = IntArray(candidates.size) { -1 }
        chosenIndices[candidates.size - 2] = bestState.first
        chosenIndices[candidates.size - 1] = bestState.second

        var state = bestState
        for (pos in candidates.size - 1 downTo 2) {
            val prev = backLayers[pos]?.get(state) ?: break
            chosenIndices[pos - 2] = prev.first
            state = prev
        }

        val result = mutableListOf<RawNote>()
        for (pos in chosenIndices.indices) {
            val idx = chosenIndices[pos]
            if (idx !in candidates[pos].second.indices) return emptyList()
            result.add(candidates[pos].second[idx])
        }
        return result
    }

    private fun cleanMelodyWithParams(
        notes: List<RawNote>,
        ticksPerBeat: Int,
        tonic: Int? = null,
        mode: String = "major"
    ): List<RawNote> {
        if (notes.isEmpty()) return emptyList()

        val segments = phraseSegments(notes, ticksPerBeat)
        val result = mutableListOf<RawNote>()
        val selectedPhrases = mutableListOf<List<RawNote>>()

        for (segment in segments) {
            val groups = buildOnsetGroups(segment, ticksPerBeat)
            var motifReference: List<RawNote>? = null

            var bestSimilarity = 0.0
            val recent = selectedPhrases.takeLast(12)
            for (previous in recent) {
                val sim = phraseSimilarity(previous, segment)
                if (sim > bestSimilarity && sim >= 0.76) {
                    bestSimilarity = sim
                    motifReference = previous
                }
            }

            val chosen = choosePhrasePath(
                groups,
                ticksPerBeat,
                tonic = tonic,
                mode = mode,
                motifReference = motifReference
            )
            if (chosen.isNotEmpty()) {
                result.addAll(chosen)
                selectedPhrases.add(chosen)
            }
        }

        result.sortBy { it.start }
        return result
    }

    fun cleanMelody(notes: List<RawNote>, ticksPerBeat: Int): List<RawNote> {
        return cleanMelodyWithParams(notes, ticksPerBeat)
    }

    fun refineMelodyWithKey(
        candidatePool: List<RawNote>,
        provisional: List<RawNote>,
        tonic: Int,
        mode: String,
        ticksPerBeat: Int
    ): List<RawNote> {
        if (candidatePool.isEmpty()) return provisional

        val refined = cleanMelodyWithParams(
            candidatePool,
            ticksPerBeat,
            tonic = tonic,
            mode = mode
        )

        if (refined.isEmpty()) return provisional

        val ratio = refined.size.toDouble() / max(1, provisional.size)
        if (ratio < 0.72) return provisional

        return refined
    }

    // ============================================================
    // 调性检测 (Krumhansl-Schmuckler 算法)
    // ============================================================

    fun detectKey(melody: List<RawNote>, allNotes: List<RawNote>): Triple<Int, String, String> {
        val source = if (melody.size >= 8) melody else allNotes
        val weights = DoubleArray(12)

        if (source.isEmpty()) {
            return Triple(0, "major", "C 大调")
        }

        val lastStart = source.maxOf { it.start }

        for (note in source) {
            val pc = ((note.pitch % 12) + 12) % 12
            val durationWeight = min(note.dur.toDouble(), 4.0 * 480.0) / 480.0
            val pitchWeight = clamp((note.pitch - 48.0) / 48.0, 0.0, 1.0)

            val tailWeight = if (note.start >= lastStart - 2 * 480) 1.28 else 1.0
            val weight = durationWeight * (1.0 + pitchWeight * 0.12) * tailWeight
            weights[pc] += weight
        }

        var bestScore = -999999.0
        var bestTonic = 0
        var bestMode = "major"
        val totalWeights = max(0.001, weights.sum())

        for (t in 0 until 12) {
            val rotated = DoubleArray(12) { i -> weights[(t + i) % 12] }

            val majorScore = pearson(rotated, MAJOR_PROFILE)
            val minorScore = pearson(rotated, MINOR_PROFILE)

            val tonicWeight = weights[t]
            val tonicScore = tonicWeight / totalWeights

            if (majorScore + tonicScore * 0.18 > bestScore) {
                bestScore = majorScore + tonicScore * 0.18
                bestTonic = t
                bestMode = "major"
            }

            if (minorScore + tonicScore * 0.18 > bestScore) {
                bestScore = minorScore + tonicScore * 0.18
                bestTonic = t
                bestMode = "minor"
            }
        }

        val modeName = if (bestMode == "major") "大调" else "小调"
        return Triple(bestTonic, bestMode, "${NOTE_NAMES[bestTonic]} $modeName")
    }

    // ============================================================
    // 白键归一化转调与八度搜索
    // ============================================================

    fun chooseNormalizationShift(notes: List<RawNote>, tonic: Int, mode: String): Int {
        if (notes.isEmpty()) return 0

        val targetTonic = if (mode == "major") 0 else 9
        val theoreticalShift = targetTonic - tonic

        var bestShift = theoreticalShift
        var bestScore = -999999.0

        for (shift in -12..12) {
            var score = 0.0
            var whiteWeight = 0.0
            var totalWeight = 0.0

            for (note in notes) {
                val weight = 1.0 + min(note.dur / 480.0, 3.0) + (note.velocity / 255.0) * 0.25
                val p = note.pitch + shift
                val pc = ((p % 12) + 12) % 12

                totalWeight += weight

                if (pc in WHITE_PITCH_CLASSES) {
                    whiteWeight += weight
                    score += 10.0 * weight
                } else {
                    var minDistance = 12
                    for (white in WHITE_PITCH_CLASSES) {
                        val d = ((pc - white) % 12 + 12) % 12
                        val d2 = min(d, 12 - d)
                        if (d2 < minDistance) minDistance = d2
                    }
                    score -= 9.0 * minDistance * weight
                }
            }

            val whiteRatio = whiteWeight / max(1e-6, totalWeight)
            val distanceFromTheory = abs(shift - theoreticalShift)
            val theoryPenalty = min(distanceFromTheory, 12) * 4.5

            val shiftedTonic = ((tonic + shift) % 12 + 12) % 12
            val targetPenalty = pitchClassDistance(shiftedTonic, targetTonic) * 5.0

            score += whiteRatio * 80.0
            score -= theoryPenalty
            score -= targetPenalty

            if (score > bestScore) {
                bestScore = score
                bestShift = shift
            }
        }

        return bestShift
    }

    private fun skyCandidates(rawPitch: Int): List<Int> {
        val candidates = mutableSetOf<Int>()

        for (octave in -2..2) {
            val base = rawPitch + octave * 12
            for (skyPitch in SKY_KEYS_MIDI) {
                if (abs(skyPitch - base) <= 3) {
                    candidates.add(skyPitch)
                }
            }
        }

        if (candidates.isEmpty()) {
            val nearest = SKY_KEYS_MIDI.sortedBy { abs(it - rawPitch) }
            candidates.addAll(nearest.take(3))
        }

        return candidates.sorted()
    }

    private fun mappingLocalCost(rawPitch: Int, mappedPitch: Int): Double {
        val diff = abs(mappedPitch - rawPitch)
        var cost = when (diff) {
            0 -> 0.0
            1 -> 1.8
            2 -> 7.0
            else -> 15.0 + diff * 2.5
        }
        if (mappedPitch == 48 || mappedPitch == 72) {
            cost += 1.2
        }
        return cost
    }

    private fun mappingTransitionCost(rawA: Int, mappedA: Int, rawB: Int, mappedB: Int): Double {
        val rawInterval = rawB - rawA
        val mappedInterval = mappedB - mappedA
        var cost = 0.0

        val intervalError = abs(mappedInterval - rawInterval)
        cost += intervalError * 3.2

        if (rawInterval > 0 && mappedInterval < 0) {
            cost += 14.0
        } else if (rawInterval < 0 && mappedInterval > 0) {
            cost += 14.0
        }

        if (rawInterval == 0 && mappedInterval != 0) {
            cost += 9.0
        }

        if (abs(mappedInterval) >= 12) cost += 8.0
        if (abs(mappedInterval) >= 17) cost += 10.0

        return cost
    }

    fun mapMelodySequence(notes: List<RawNote>, normalizationShift: Int, octaveShift: Int): List<Pair<RawNote, Int>> {
        if (notes.isEmpty()) return emptyList()

        val rawPitches = notes.map { it.pitch + normalizationShift + octaveShift * 12 }
        val candidates = rawPitches.map { skyCandidates(it) }

        val dp = mutableListOf<DoubleArray>()
        val back = mutableListOf<IntArray>()

        for (i in candidates.indices) {
            val candList = candidates[i]
            val row = DoubleArray(candList.size) { Double.POSITIVE_INFINITY }
            val rowBack = IntArray(candList.size) { -1 }

            for (ci in candList.indices) {
                val mappedPitch = candList[ci]
                val localCost = mappingLocalCost(rawPitches[i], mappedPitch)

                if (i == 0) {
                    row[ci] = localCost
                    continue
                }

                val prevCandList = candidates[i - 1]
                for (pi in prevCandList.indices) {
                    val prevMappedPitch = prevCandList[pi]
                    val transition = mappingTransitionCost(
                        rawPitches[i - 1],
                        prevMappedPitch,
                        rawPitches[i],
                        mappedPitch
                    )
                    val total = dp[i - 1][pi] + localCost + transition
                    if (total < row[ci]) {
                        row[ci] = total
                        rowBack[ci] = pi
                    }
                }
            }

            dp.add(row)
            back.add(rowBack)
        }

        val lastRow = dp.last()
        var bestIndex = 0
        var minLastCost = lastRow[0]
        for (i in 1 until lastRow.size) {
            if (lastRow[i] < minLastCost) {
                minLastCost = lastRow[i]
                bestIndex = i
            }
        }

        val mapped = IntArray(notes.size)
        for (i in notes.size - 1 downTo 0) {
            mapped[i] = candidates[i][bestIndex]
            bestIndex = back[i][bestIndex]
        }

        return notes.mapIndexed { idx, note -> Pair(note, mapped[idx]) }
    }

    fun chooseBestOctaveShift(notes: List<RawNote>, normalizationShift: Int): Int {
        if (notes.isEmpty()) return 0

        var bestShift = 0
        var bestScore = Double.POSITIVE_INFINITY

        for (octaveShift in -4..4) {
            val raw = notes.map { it.pitch + normalizationShift + octaveShift * 12 }
            var outPenalty = 0.0
            var edgePenalty = 0.0

            for (p in raw) {
                if (p < 48) outPenalty += (48 - p) * 8.0
                else if (p > 72) outPenalty += (p - 72) * 8.0

                if (p in 48..72 && (p <= 50 || p >= 70)) {
                    edgePenalty += 0.8
                }
            }

            val mappedPairs = mapMelodySequence(notes, normalizationShift, octaveShift)
            var mappingError = 0.0
            for (idx in raw.indices) {
                mappingError += abs(raw[idx] - mappedPairs[idx].second)
            }

            val score = outPenalty * 1.0 + mappingError * 5.0 + edgePenalty
            if (score < bestScore) {
                bestScore = score
                bestShift = octaveShift
            }
        }

        return bestShift
    }

    // ============================================================
    // 节奏网格与事件序列生成
    // ============================================================

    fun chooseRhythmGrid(notes: List<RawNote>, ticksPerBeat: Int): Long {
        if (notes.size < 4) return max(1L, (ticksPerBeat / 4).toLong())

        val starts = notes.map { it.start }.distinct().sorted()
        if (starts.size < 3) return max(1L, (ticksPerBeat / 4).toLong())

        val candidates = listOf(
            max(1L, (ticksPerBeat / 2).toLong()),
            max(1L, (ticksPerBeat / 3).toLong()),
            max(1L, (ticksPerBeat / 4).toLong()),
            max(1L, (ticksPerBeat / 6).toLong()),
            max(1L, (ticksPerBeat / 8).toLong())
        ).distinct()

        var bestGrid = candidates.getOrElse(2) { candidates[0] }
        var bestScore = Double.POSITIVE_INFINITY

        for (grid in candidates) {
            val errors = starts.map { abs(it - snapGrid(it, grid)) }
            val meanError = errors.average()
            val exactRatio = errors.count { it == 0L }.toDouble() / errors.size

            val slotsPerBeat = max(1.0, ticksPerBeat.toDouble() / grid)
            val complexity = 0.55 * max(0.0, slotsPerBeat - 4.0)

            val musicalPrior = if (grid == (ticksPerBeat / 4).toLong()) -0.35 else 0.0
            val score = meanError - exactRatio * min(grid * 0.18, 8.0) + complexity + musicalPrior

            if (score < bestScore) {
                bestScore = score
                bestGrid = grid
            }
        }

        return max(1L, bestGrid)
    }

    private fun applyMotifConsistency(notes: List<RawNote>, ticksPerBeat: Int): List<RawNote> {
        if (notes.size < 12) return notes

        val phrases = phraseSegments(notes, ticksPerBeat)
        if (phrases.size < 2) return notes

        val flattened = mutableListOf<RawNote>()
        for (phrase in phrases) {
            flattened.addAll(phrase)
        }

        val result = flattened.toMutableList()
        for (i in 1 until result.size - 1) {
            val a = result[i - 1].pitch
            val b = result[i].pitch
            val c = result[i + 1].pitch
            if (abs(b - a) >= 19 && abs(c - b) >= 19) continue
            if (abs(b - a) >= 19 && abs(c - b) <= 4) continue
        }
        return result
    }

    fun buildMelodyEvents(
        notes: List<RawNote>,
        normalizationShift: Int,
        octaveShift: Int,
        ticksPerBeat: Int
    ): Pair<List<MelodyEvent>, Long> {
        if (notes.isEmpty()) return Pair(emptyList(), max(1L, (ticksPerBeat / 4).toLong()))

        val motifNotes = applyMotifConsistency(notes, ticksPerBeat)
        val mappedPairs = mapMelodySequence(motifNotes, normalizationShift, octaveShift)
        val grid = chooseRhythmGrid(motifNotes, ticksPerBeat)
        val result = mutableListOf<MelodyEvent>()

        for (i in mappedPairs.indices) {
            val (note, mappedPitch) = mappedPairs[i]
            val start = snapGrid(note.start, grid)
            var quantizedDur = max(grid, snapGrid(note.dur, grid))

            // 单音旋律防重叠粘音
            if (i + 1 < mappedPairs.size) {
                val nextStart = snapGrid(mappedPairs[i + 1].first.start, grid)
                if (nextStart > start) {
                    quantizedDur = min(quantizedDur, nextStart - start)
                }
            }

            val keyIndex = SKY_KEYS_MIDI.indexOf(mappedPitch).coerceIn(0, 14)

            result.add(
                MelodyEvent(
                    key = keyIndex,
                    pitch = mappedPitch,
                    originalPitch = note.pitch,
                    start = start,
                    end = start + max(grid, quantizedDur),
                    dur = max(grid, quantizedDur),
                    velocity = note.velocity,
                    isMelody = true
                )
            )
        }

        // 同一网格起点冲突处理
        val grouped = result.groupBy { it.start }
        val final = mutableListOf<MelodyEvent>()

        for (start in grouped.keys.sorted()) {
            val group = grouped[start]!!
            if (group.size == 1) {
                final.add(group[0])
                continue
            }

            val prevPitch = final.lastOrNull()?.pitch
            var nextPitch: Int? = null
            for (s2 in grouped.keys.sorted()) {
                if (s2 > start) {
                    nextPitch = grouped[s2]!!.minByOrNull { abs(it.pitch - (prevPitch ?: it.pitch)) }?.pitch
                    break
                }
            }

            val best = group.minWithOrNull { a, b ->
                val contA = if (prevPitch != null) abs(a.pitch - prevPitch).toDouble() else 0.0
                val futA = if (nextPitch != null) abs(nextPitch - a.pitch).toDouble() else 0.0
                val rankA = contA * 0.65 + futA * 0.35

                val contB = if (prevPitch != null) abs(b.pitch - prevPitch).toDouble() else 0.0
                val futB = if (nextPitch != null) abs(nextPitch - b.pitch).toDouble() else 0.0
                val rankB = contB * 0.65 + futB * 0.35

                val c1 = rankA.compareTo(rankB)
                if (c1 != 0) return@minWithOrNull c1
                val c2 = b.dur.compareTo(a.dur)
                if (c2 != 0) return@minWithOrNull c2
                b.velocity.compareTo(a.velocity)
            }!!

            final.add(best)
        }

        return Pair(final, grid)
    }

    fun buildBassEvents(
        accompaniment: List<RawNote>,
        normalizationShift: Int,
        octaveShift: Int,
        ticksPerBeat: Int,
        melodyEvents: List<MelodyEvent>,
        grid: Long
    ): List<MelodyEvent> {
        if (accompaniment.isEmpty()) return emptyList()

        val strongInterval = max(grid * 2, ticksPerBeat.toLong())
        val minInterval = max(grid * 2, ticksPerBeat.toLong())
        val melodyStarts = melodyEvents.map { it.start }.toSet()
        val grouped = mutableMapOf<Long, MutableList<MelodyEvent>>()

        for (note in accompaniment) {
            val shifted = note.pitch + normalizationShift + octaveShift * 12
            if (shifted > 67) continue

            // 最近白键
            var pitch = SKY_KEYS_MIDI.minByOrNull { abs(it - shifted) } ?: 48
            while (pitch < 48) pitch += 12
            while (pitch > 59) pitch -= 12
            if (pitch !in 48..59) continue

            val start = snapGrid(note.start, grid)
            val keyIndex = SKY_KEYS_MIDI.indexOf(pitch).coerceIn(0, 14)

            val event = MelodyEvent(
                key = keyIndex,
                pitch = pitch,
                originalPitch = note.pitch,
                start = start,
                end = start + max(grid, snapGrid(note.dur, grid)),
                dur = max(grid, snapGrid(note.dur, grid)),
                velocity = note.velocity,
                isMelody = false
            )
            grouped.getOrPut(start) { mutableListOf() }.add(event)
        }

        val result = mutableListOf<MelodyEvent>()
        var last = -999999L

        for (start in grouped.keys.sorted()) {
            if (start - last < minInterval) continue
            // 旋律起点让位
            if (start in melodyStarts) continue

            val candidates = grouped[start]!!
            if (candidates.isEmpty()) continue

            candidates.sortWith(
                compareBy<MelodyEvent> { it.pitch }
                    .thenByDescending { it.dur }
                    .thenByDescending { it.velocity }
            )

            val event = candidates[0]
            val beatPos = start % strongInterval
            if (beatPos != 0L && result.isEmpty()) continue
            if (beatPos != 0L && result.isNotEmpty() && start - result.last().start < strongInterval) continue

            result.add(event)
            last = start
        }

        return result
    }

    fun mergeEvents(melodyEvents: List<MelodyEvent>, bassEvents: List<MelodyEvent>): List<MelodyEvent> {
        val result = melodyEvents.toMutableList()
        val melodyStarts = melodyEvents.map { it.start }.toSet()

        for (bass in bassEvents) {
            if (bass.start in melodyStarts) {
                val samePitch = melodyEvents.any { it.start == bass.start && it.pitch == bass.pitch }
                if (samePitch) continue
            }
            result.add(bass)
        }

        result.sortWith(
            compareBy<MelodyEvent> { it.start }
                .thenBy { !it.isMelody }
                .thenBy { it.pitch }
        )
        return result
    }

    // ============================================================
    // 兼容历史接口与底层解码辅助
    // ============================================================

    fun pitchToSkyKey(pitch: Int, root: Int = 0, octaveShift: Int = 0): Int {
        val target = pitch + octaveShift * 12
        var nearestKey = 0
        var minDiff = Int.MAX_VALUE
        for (i in SKY_KEYS_MIDI.indices) {
            val diff = abs(SKY_KEYS_MIDI[i] - target)
            if (diff < minDiff) {
                minDiff = diff
                nearestKey = i
            }
        }
        return nearestKey.coerceIn(0, 14)
    }

    fun foldPitchToSkyKey(pitch: Int): Int {
        return pitchToSkyKey(pitch, 0, 0)
    }

    private fun decodeMidiText(bytes: ByteArray): String {
        return try {
            val utf8 = String(bytes, Charsets.UTF_8)
            if (!utf8.contains('\uFFFD')) {
                utf8
            } else {
                String(bytes, Charset.forName("GBK"))
            }
        } catch (e: Exception) {
            try {
                String(bytes, Charset.forName("GBK"))
            } catch (e2: Exception) {
                String(bytes)
            }
        }
    }

    private fun readVariableLength(buffer: ByteBuffer): Long {
        var value = 0L
        var byte: Int
        do {
            if (!buffer.hasRemaining()) break
            byte = buffer.get().toInt() and 0xFF
            value = (value shl 7) or (byte and 0x7F).toLong()
        } while ((byte and 0x80) != 0)
        return value
    }

    private fun tickToMillis(targetTick: Long, ppq: Int, tempoChanges: List<TempoChange>): Long {
        if (targetTick <= 0L) return 0L
        var elapsedMs = 0.0
        var currentTick = 0L
        var currentUsPerQuarter = tempoChanges.firstOrNull()?.usPerQuarter ?: 500_000L

        for (i in tempoChanges.indices) {
            val change = tempoChanges[i]
            if (targetTick <= change.tick) {
                break
            }
            val deltaTicks = change.tick - currentTick
            if (deltaTicks > 0) {
                elapsedMs += (deltaTicks.toDouble() * currentUsPerQuarter.toDouble()) / (ppq.toDouble() * 1000.0)
                currentTick = change.tick
            }
            currentUsPerQuarter = change.usPerQuarter
        }

        val remainingTicks = targetTick - currentTick
        if (remainingTicks > 0) {
            elapsedMs += (remainingTicks.toDouble() * currentUsPerQuarter.toDouble()) / (ppq.toDouble() * 1000.0)
        }

        return elapsedMs.roundToLong()
    }
}
