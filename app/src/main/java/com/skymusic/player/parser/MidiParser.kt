package com.skymusic.player.parser

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object MidiParser {

    private data class RawMidiNote(
        val tick: Long,
        val noteNumber: Int, // 0..127
        val velocity: Int,
        val channel: Int
    )

    private data class TempoChange(
        val tick: Long,
        val usPerQuarter: Long
    )

    /**
     * Krumhansl-Schmuckler 音乐理论经典调性音高相关权重矩阵
     */
    private val MAJOR_PROFILE = doubleArrayOf(
        6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88
    )
    private val MINOR_PROFILE = doubleArrayOf(
        6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17
    )
    private val DIATONIC_SET = setOf(0, 2, 4, 5, 7, 9, 11)

    /**
     * 光遇标准 15 键对应的标准 MIDI 音高（C4 到 C6 自然大调音阶）：
     * Key 0..4  (Row 0): C4 (60), D4 (62), E4 (64), F4 (65), G4 (67)
     * Key 5..9  (Row 1): A4 (69), B4 (71), C5 (72), D5 (74), E5 (76)
     * Key 10..14(Row 2): F5 (77), G5 (79), A5 (81), B5 (83), C6 (84)
     */
    val SKY_KEY_PITCHES = intArrayOf(
        60, 62, 64, 65, 67, 69, 71, // Key 0..6 (1, 2, 3, 4, 5, 6, 7)
        72, 74, 76, 77, 79, 81, 83, // Key 7..13 (+1, +2, +3, +4, +5, +6, +7)
        84                          // Key 14 (++1)
    )

    /**
     * 解析标准 MIDI 文件输入流并完成高保真光遇 15 键智能音符映射
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
        val division = buffer.short.toInt() // PPQ (Ticks per Quarter Note)
        val ppq = if (division > 0) division else 480

        // 跳过 header 中多余字节（如果有）
        if (headerSize > 6) {
            buffer.position(buffer.position() + (headerSize - 6))
        }

        val rawNotes = mutableListOf<RawMidiNote>()
        val tempoChanges = mutableListOf<TempoChange>()
        tempoChanges.add(TempoChange(0L, 500_000L)) // 默认 120 BPM = 500,000 微秒/拍

        var songTitle = defaultTitle

        // 2. 读取每个 Track 块
        for (t in 0 until numTracks) {
            if (buffer.remaining() < 8) break
            val trackId = ByteArray(4)
            buffer.get(trackId)
            val trackLength = buffer.int
            val trackEndPos = buffer.position() + trackLength

            var currentTick = 0L
            var runningStatus = 0

            while (buffer.position() < trackEndPos && buffer.hasRemaining()) {
                // 读取变长 Delta Time
                val delta = readVariableLength(buffer)
                currentTick += delta

                if (!buffer.hasRemaining()) break
                var status = buffer.get().toInt() and 0xFF

                if (status < 0x80) {
                    // Running status
                    if (runningStatus == 0) {
                        break
                    }
                    status = runningStatus
                    buffer.position(buffer.position() - 1)
                } else {
                    // 仅当状态字节为通道消息 (0x80..0xEF) 时记录运行状态
                    // 遇到 Meta 事件 (0xFF) 或 SysEx (0xF0..0xF7) 必须复位
                    if (status < 0xF0) {
                        runningStatus = status
                    } else {
                        runningStatus = 0
                    }
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
                        0x03 -> { // Track Name / Song Title
                            val name = String(metaData).trim()
                            if (name.isNotEmpty() && (songTitle == defaultTitle || songTitle.isBlank())) {
                                songTitle = name
                            }
                        }
                        0x51 -> { // Set Tempo (3 字节微秒/四分音符)
                            if (metaLen >= 3) {
                                val us = ((metaData[0].toInt() and 0xFF) shl 16) or
                                        ((metaData[1].toInt() and 0xFF) shl 8) or
                                        (metaData[2].toInt() and 0xFF)
                                tempoChanges.add(TempoChange(currentTick, us.toLong()))
                            }
                        }
                    }
                } else if (status == 0xF0 || status == 0xF7) {
                    // SysEx 事件
                    val sysexLen = readVariableLength(buffer).toInt()
                    if (buffer.remaining() >= sysexLen) {
                        buffer.position(buffer.position() + sysexLen)
                    } else {
                        buffer.position(buffer.limit())
                    }
                } else {
                    // 常用 Channel 消息
                    val msgType = status and 0xF0
                    val channel = status and 0x0F
                    when (msgType) {
                        0x90 -> { // Note On
                            if (buffer.remaining() >= 2) {
                                val note = buffer.get().toInt() and 0xFF
                                val vel = buffer.get().toInt() and 0xFF
                                // 关键校准 1：严格过滤 Channel 9 (第10轨道打击乐/鼓点)，排除底鼓、军鼓对旋律的严重杂音污染
                                if (vel > 0 && channel != 9) {
                                    rawNotes.add(RawMidiNote(currentTick, note, vel, channel))
                                }
                            }
                        }
                        0x80 -> { // Note Off
                            if (buffer.remaining() >= 2) {
                                buffer.get()
                                buffer.get()
                            }
                        }
                        0xA0, 0xB0, 0xE0 -> { // 2 字节参数消息
                            if (buffer.remaining() >= 2) {
                                buffer.get()
                                buffer.get()
                            }
                        }
                        0xC0, 0xD0 -> { // 1 字节参数消息
                            if (buffer.hasRemaining()) {
                                buffer.get()
                            }
                        }
                    }
                }
            }

            buffer.position(trackEndPos.coerceAtMost(buffer.limit()))
        }

        if (rawNotes.isEmpty()) {
            return Song(
                id = UUID.randomUUID().toString(),
                title = songTitle,
                artist = "MIDI 转换",
                bpm = 120,
                notes = emptyList(),
                durationMs = 0L,
                type = "MIDI"
            )
        }

        // 3. 排序 Tempo 列表并计算每个 Tick 对应的绝对毫秒时间戳
        tempoChanges.sortBy { it.tick }
        val timedNotes = rawNotes.map { note ->
            val ms = tickToMillis(note.tick, ppq, tempoChanges)
            Triple(ms, note.noteNumber, note.velocity)
        }.sortedBy { it.first }

        // 4. 关键校准 2：使用 Krumhansl-Schmuckler 算法进行调性与主音精确分析
        // 将原曲主音 (Tonic) 严格对齐至光遇的自然大调 (C大调，Key 0/7/14 = Do) 或自然小调 (A小调，Key 5/12 = La)
        val optimalTranspose = findOptimalTranspose(timedNotes.map { it.second })

        // 5. 关键校准 3：全曲全局最佳基准八度偏移探测
        // 计算让最多音符无需折叠即可自然落入 [60, 84] (C4 ~ C6) 的最佳八度
        val transposedPitches = timedNotes.map { it.second + optimalTranspose }
        val baseOctaveShift = findBestBaseOctave(transposedPitches)

        // 6. 关键校准 4：八度循环折叠（Octave Folding）彻底废除 0/14 截断
        // 将超出 15 键范围的高音和低音伴奏，按 12 半音精确循环内折，保留原有 1 2 3 4 5 6 7 唱名
        // 7. 关键校准 5：和弦时间窗聚合 (30ms) 与声部精炼 (单次手势上限 4 键，锁定主旋律高音与根音低音)
        val timeMap = mutableMapOf<Long, MutableList<Int>>()

        for ((ms, pitch, _) in timedNotes) {
            val fullPitch = pitch + optimalTranspose + baseOctaveShift
            val keyIndex = foldPitchToSkyKey(fullPitch)

            if (keyIndex in 0..14) {
                // 30ms 时间窗口聚合，将真人/吉他扫弦/微落差音符精准整合成和弦
                val quantizedTime = Math.round(ms / 30.0) * 30L
                val keys = timeMap.getOrPut(quantizedTime) { mutableListOf() }
                if (!keys.contains(keyIndex)) {
                    keys.add(keyIndex)
                }
            }
        }

        val noteEvents = mutableListOf<NoteEvent>()
        for ((time, rawKeys) in timeMap) {
            // 对单次和弦做声部精炼：优先保留最高音（主旋律）与最低音（低音伴奏根音）
            val refinedKeys = refineChordKeys(rawKeys)
            if (refinedKeys.isNotEmpty()) {
                noteEvents.add(NoteEvent(timeMs = time, keys = refinedKeys))
            }
        }
        noteEvents.sort()

        val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L

        // 计算平均 BPM
        val avgTempoUs = if (tempoChanges.isNotEmpty()) tempoChanges.first().usPerQuarter else 500_000L
        val bpm = (60_000_000L / avgTempoUs).toInt().coerceIn(40, 240)

        return Song(
            id = UUID.randomUUID().toString(),
            title = songTitle,
            artist = "MIDI 转换",
            bpm = bpm,
            notes = noteEvents,
            durationMs = duration,
            type = "MIDI"
        )
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
        var elapsedMs = 0.0
        var currentTick = 0L
        var currentUsPerQuarter = tempoChanges[0].usPerQuarter

        for (i in 0 until tempoChanges.size) {
            val change = tempoChanges[i]
            if (targetTick <= change.tick) {
                break
            }
            val deltaTicks = change.tick - currentTick
            elapsedMs += (deltaTicks.toDouble() * currentUsPerQuarter.toDouble()) / (ppq.toDouble() * 1000.0)
            currentTick = change.tick
            currentUsPerQuarter = change.usPerQuarter
        }

        val remainingTicks = targetTick - currentTick
        elapsedMs += (remainingTicks.toDouble() * currentUsPerQuarter.toDouble()) / (ppq.toDouble() * 1000.0)

        return elapsedMs.toLong()
    }

    /**
     * Krumhansl-Schmuckler 调性检测算法：
     * 精确统计 12 个半音出现频度，计算与大调/小调标准轮廓的相关系数，
     * 找到歌曲的主音（Tonic）与调式，并返回将其移调到 C 大调 (Do) / A 小调 (La) 的最优半音位移 (-6..+6)。
     */
    private fun findOptimalTranspose(pitches: List<Int>): Int {
        if (pitches.isEmpty()) return 0

        val counts = DoubleArray(12)
        for (p in pitches) {
            val pc = ((p % 12) + 12) % 12
            counts[pc] += 1.0
        }

        var bestScore = -9999.0
        var bestShift = 0

        for (tonic in 0 until 12) {
            val rotated = DoubleArray(12) { i -> counts[(tonic + i) % 12] }
            val scoreMajor = calcPearsonCorrelation(rotated, MAJOR_PROFILE)
            val scoreMinor = calcPearsonCorrelation(rotated, MINOR_PROFILE)

            if (scoreMajor > bestScore) {
                bestScore = scoreMajor
                var shift = (12 - tonic) % 12
                if (shift > 6) shift -= 12
                bestShift = shift
            }
            if (scoreMinor > bestScore) {
                bestScore = scoreMinor
                var shift = (9 - tonic) % 12
                if (shift > 6) shift -= 12
                bestShift = shift
            }
        }

        // 双重校验：若最大相关性得出的移调在白键命中率上不足 70%，回退到贪心白键最大化匹配
        val testHits = pitches.count { ((it + bestShift) % 12 + 12) % 12 in DIATONIC_SET }
        if (testHits.toDouble() / pitches.size < 0.70) {
            var fallbackShift = 0
            var maxHits = -1
            for (s in -6..6) {
                val h = pitches.count { ((it + s) % 12 + 12) % 12 in DIATONIC_SET }
                if (h > maxHits) {
                    maxHits = h
                    fallbackShift = s
                }
            }
            return fallbackShift
        }

        return bestShift
    }

    private fun calcPearsonCorrelation(x: DoubleArray, y: DoubleArray): Double {
        val n = 12
        var sumX = 0.0
        var sumY = 0.0
        for (i in 0 until n) {
            sumX += x[i]
            sumY += y[i]
        }
        val meanX = sumX / n
        val meanY = sumY / n

        var num = 0.0
        var denX = 0.0
        var denY = 0.0
        for (i in 0 until n) {
            val dx = x[i] - meanX
            val dy = y[i] - meanY
            num += dx * dy
            denX += dx * dx
            denY += dy * dy
        }
        val den = Math.sqrt(denX * denY)
        return if (den == 0.0) 0.0 else num / den
    }

    /**
     * 计算最佳基准八度偏移 (-24, -12, 0, +12, +24)，使得最多音符自然落在 [60, 84] (C4 ~ C6) 内
     */
    private fun findBestBaseOctave(pitches: List<Int>): Int {
        if (pitches.isEmpty()) return 0
        var bestOct = 0
        var maxDirectHits = -1

        for (oct in intArrayOf(-24, -12, 0, 12, 24)) {
            val inRangeCount = pitches.count { (it + oct) in 60..84 }
            if (inRangeCount > maxDirectHits) {
                maxDirectHits = inRangeCount
                bestOct = oct
            }
        }
        return bestOct
    }

    /**
     * 智能八度循环折叠（Octave Folding）：
     * 将任意音高通过 +/-12 循环折叠入 [60, 84]，并精确映射到光遇 15 个自然音阶按键。
     * 彻底废除原先粗暴的 return 0 和 return 14！
     */
    fun foldPitchToSkyKey(pitch: Int): Int {
        var p = pitch
        while (p < 60) p += 12
        while (p > 84) p -= 12

        // 精确匹配 15 键
        var bestKey = 0
        var minDiff = Int.MAX_VALUE
        for (i in SKY_KEY_PITCHES.indices) {
            val diff = Math.abs(p - SKY_KEY_PITCHES[i])
            if (diff < minDiff) {
                minDiff = diff
                bestKey = i
                if (diff == 0) break // 精准命中白键自然音阶，立即返回
            }
        }
        return bestKey
    }

    /**
     * 和弦声部精炼：
     * 限制单次并发手势上限为 3~4 键（光遇推荐多指上限）。
     * 自动保留最高音（主旋律）、最低音（和弦低音根音）以及中声部主要和声，剔除冗余同音。
     */
    private fun refineChordKeys(keys: List<Int>): List<Int> {
        val distinctKeys = keys.distinct().sorted()
        if (distinctKeys.size <= 4) {
            return distinctKeys
        }

        // 超过 4 键时精炼：保留最低音、最高音和中间 1~2 个音
        val result = mutableListOf<Int>()
        result.add(distinctKeys.first()) // 低音根音
        result.add(distinctKeys.last())  // 主旋律高音

        val middle = distinctKeys.subList(1, distinctKeys.size - 1)
        if (middle.size == 1) {
            result.add(middle[0])
        } else if (middle.size >= 2) {
            result.add(middle[0])
            result.add(middle.last())
        }

        return result.distinct().sorted()
    }
}
