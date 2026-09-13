package com.skymusic.player.parser

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object MidiParser {

    private data class ParsedNote(
        val pitch: Int,
        val startTick: Long,
        val durationTicks: Long,
        val velocity: Int,
        val channel: Int,
        val trackIndex: Int
    )

    private data class TempoChange(
        val tick: Long,
        val usPerQuarter: Long
    )

    private data class ProcessedEvent(
        val startTick: Long,
        val timeMs: Long,
        val keyIndex: Int,
        val isMelody: Boolean
    )

    // C 大调自然音级 (C, D, E, F, G, A, B)
    private val NATURAL_NOTES = setOf(0, 2, 4, 5, 7, 9, 11)

    // 光遇 15 键对应的标准 MIDI 音高（C3=48 体系：低音1到高音1'）
    // 实际覆盖范围为 C3(48) 到 C5(72) 的自然大调音阶
    private val SKY_KEYS = intArrayOf(48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72)

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
     * 具备 demo.py 启发式主旋律识别、全局白键移调优化、声部音区独立折叠与伴奏和弦稀疏化（消除复杂优化）
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

        val tracksNotes = mutableListOf<List<ParsedNote>>()
        val tempoChanges = mutableListOf<TempoChange>()
        tempoChanges.add(TempoChange(0L, 500_000L)) // 默认 120 BPM = 500,000 微秒/拍

        var songTitle = defaultTitle

        // 2. 逐音轨解析（提取音符绝对 Tick、声部与时长，严格过滤打击乐）
        for (t in 0 until numTracks) {
            if (buffer.remaining() < 8) break
            val trackId = ByteArray(4)
            buffer.get(trackId)
            val trackLength = buffer.int
            val trackEndPos = buffer.position() + trackLength

            var currentTick = 0L
            var runningStatus = 0
            val trackNotes = mutableListOf<ParsedNote>()
            // key: (channel, noteNumber) -> value: (startTick, velocity)
            val activeNotes = mutableMapOf<Pair<Int, Int>, Pair<Long, Int>>()

            while (buffer.position() < trackEndPos && buffer.hasRemaining()) {
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
                    // Channel 消息
                    val msgType = status and 0xF0
                    val channel = status and 0x0F
                    when (msgType) {
                        0x90 -> { // Note On
                            if (buffer.remaining() >= 2) {
                                val note = buffer.get().toInt() and 0xFF
                                val vel = buffer.get().toInt() and 0xFF
                                // 过滤 Channel 9 (第10轨道打击乐/鼓点)
                                if (channel != 9) {
                                    val key = Pair(channel, note)
                                    if (vel > 0) {
                                        val prev = activeNotes[key]
                                        if (prev != null) {
                                            val dur = (currentTick - prev.first).coerceAtLeast(1L)
                                            trackNotes.add(ParsedNote(note, prev.first, dur, prev.second, channel, t))
                                        }
                                        activeNotes[key] = Pair(currentTick, vel)
                                    } else {
                                        val prev = activeNotes.remove(key)
                                        if (prev != null) {
                                            val dur = (currentTick - prev.first).coerceAtLeast(1L)
                                            trackNotes.add(ParsedNote(note, prev.first, dur, prev.second, channel, t))
                                        }
                                    }
                                }
                            }
                        }
                        0x80 -> { // Note Off
                            if (buffer.remaining() >= 2) {
                                val note = buffer.get().toInt() and 0xFF
                                buffer.get() // velocity
                                if (channel != 9) {
                                    val key = Pair(channel, note)
                                    val prev = activeNotes.remove(key)
                                    if (prev != null) {
                                        val dur = (currentTick - prev.first).coerceAtLeast(1L)
                                        trackNotes.add(ParsedNote(note, prev.first, dur, prev.second, channel, t))
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

            // 处理可能未显式 NoteOff 的悬空尾音
            for ((key, pair) in activeNotes) {
                val (startTick, vel) = pair
                val dur = ppq.toLong()
                trackNotes.add(ParsedNote(key.second, startTick, dur, vel, key.first, t))
            }

            if (trackNotes.isNotEmpty()) {
                tracksNotes.add(trackNotes)
            }

            buffer.position(trackEndPos.coerceAtMost(buffer.limit()))
        }

        if (tracksNotes.isEmpty()) {
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

        // 3. 全局最佳移调优化（遍历 -6 到 +6 半音，白键 +1，黑键 -3 严厉扣分）
        val allFlatNotes = tracksNotes.flatten()
        val bestShift = findBestTranspose(allFlatNotes)

        // 4. 启发式主旋律识别与声部分流（Melody vs Accompaniment）
        val melodyNotes = mutableListOf<ParsedNote>()
        val accompanimentNotes = mutableListOf<ParsedNote>()

        if (tracksNotes.size > 1) {
            val trackScores = tracksNotes.mapIndexed { index, notes ->
                Pair(index, scoreTrackForMelody(notes))
            }.sortedByDescending { it.second }
            val melodyTrackIdx = trackScores.first().first

            for (i in tracksNotes.indices) {
                if (i == melodyTrackIdx) {
                    melodyNotes.addAll(tracksNotes[i])
                } else {
                    accompanimentNotes.addAll(tracksNotes[i])
                }
            }
        } else {
            // 单轨 MIDI (如 Type 0)：若包含多通道则按通道分流，否则按时间戳最高音为旋律
            val singleTrack = tracksNotes[0]
            val channels = singleTrack.map { it.channel }.distinct()
            if (channels.size > 1) {
                val channelGroups = singleTrack.groupBy { it.channel }.values.toList()
                val chScores = channelGroups.mapIndexed { index, notes ->
                    Pair(index, scoreTrackForMelody(notes))
                }.sortedByDescending { it.second }
                val melodyChIdx = chScores.first().first

                for (i in channelGroups.indices) {
                    if (i == melodyChIdx) {
                        melodyNotes.addAll(channelGroups[i])
                    } else {
                        accompanimentNotes.addAll(channelGroups[i])
                    }
                }
            } else {
                val byStart = singleTrack.groupBy { it.startTick }
                for ((_, group) in byStart) {
                    val sorted = group.sortedByDescending { it.pitch }
                    melodyNotes.add(sorted.first())
                    if (sorted.size > 1) {
                        accompanimentNotes.addAll(sorted.drop(1))
                    }
                }
            }
        }

        // 5. 处理旋律音（移调 + 中高音区独立折叠 [57..72]）
        tempoChanges.sortBy { it.tick }
        val processedEvents = mutableListOf<ProcessedEvent>()

        for (n in melodyNotes) {
            val shifted = n.pitch + bestShift
            val skyKey = fitToSkyKey(shifted, isMelody = true)
            val timeMs = tickToMillis(n.startTick, ppq, tempoChanges)
            processedEvents.add(ProcessedEvent(n.startTick, timeMs, skyKey, isMelody = true))
        }

        // 6. 处理伴奏音：强行抽稀（消除复杂优化，至少间隔半拍避免砸琴；同时间戳只取最低音根音；低音区独立折叠 [48..60]）
        val sortedAcc = accompanimentNotes.sortedWith(
            compareBy<ParsedNote> { it.startTick }.thenBy { it.pitch }
        )
        val minIntervalTicks = (ppq / 2).coerceAtLeast(1)
        var lastAccTick = -999_999L

        for (n in sortedAcc) {
            if (n.startTick - lastAccTick >= minIntervalTicks) {
                val shifted = n.pitch + bestShift
                val skyKey = fitToSkyKey(shifted, isMelody = false)
                val timeMs = tickToMillis(n.startTick, ppq, tempoChanges)
                processedEvents.add(ProcessedEvent(n.startTick, timeMs, skyKey, isMelody = false))
                lastAccTick = n.startTick
            }
        }

        // 7. 合并并按时间排序
        processedEvents.sortBy { it.timeMs }

        // 8. 25ms 时间窗微聚合（支持主旋律与伴奏根音构成干净双音/三音和弦）
        val timeMap = mutableMapOf<Long, MutableList<Int>>()
        for (ev in processedEvents) {
            val quantizedTime = Math.round(ev.timeMs / 25.0) * 25L
            val keys = timeMap.getOrPut(quantizedTime) { mutableListOf() }
            if (!keys.contains(ev.keyIndex)) {
                keys.add(ev.keyIndex)
            }
        }

        val noteEvents = mutableListOf<NoteEvent>()
        for ((time, rawKeys) in timeMap) {
            val distinctSorted = rawKeys.distinct().sorted()
            val refined = if (distinctSorted.size <= 3) {
                distinctSorted
            } else {
                listOf(distinctSorted.first(), distinctSorted[distinctSorted.size / 2], distinctSorted.last()).distinct().sorted()
            }
            if (refined.isNotEmpty()) {
                noteEvents.add(NoteEvent(timeMs = time, keys = refined))
            }
        }
        noteEvents.sort()

        val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L
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

    /**
     * 全局移调优化：遍历 -6 到 +6 半音，找出落入自然白键最多的移调量
     */
    private fun findBestTranspose(allNotes: List<ParsedNote>): Int {
        var bestShift = 0
        var maxScore = Int.MIN_VALUE
        for (shift in -6..6) {
            var score = 0
            for (n in allNotes) {
                val pitchClass = ((n.pitch + shift) % 12 + 12) % 12
                if (pitchClass in NATURAL_NOTES) {
                    score += 1 // 命中白键加分
                } else {
                    score -= 3 // 命中了黑键（半音）重罚
                }
            }
            if (score > maxScore || (score == maxScore && Math.abs(shift) < Math.abs(bestShift))) {
                maxScore = score
                bestShift = shift
            }
        }
        return bestShift
    }

    /**
     * 旋律识别启发式评分：
     * 主旋律特征：音高相对较高、多音重叠率低（单音纯净线条）、适度音符量覆盖全曲
     */
    private fun scoreTrackForMelody(notes: List<ParsedNote>): Double {
        if (notes.isEmpty()) return -1.0
        val avgPitch = notes.map { it.pitch }.average()
        val timePoints = notes.map { it.startTick }
        val overlapCount = timePoints.size - timePoints.toSet().size
        val polyphonyRate = overlapCount.toDouble() / notes.size.toDouble()
        val noteBonus = Math.min(notes.size, 400) * 0.02
        return (avgPitch * 0.6) - (polyphonyRate * 50.0) + noteBonus
    }

    /**
     * 将音高折叠并强制吸附到光遇 15 键 (0..14)
     * - 旋律区优先保留在中高音区 (57~72，即 key 5..14)
     * - 伴奏区保留在低音区 (48~60，即 key 0..7)
     */
    fun fitToSkyKey(pitch: Int, isMelody: Boolean): Int {
        var p = pitch
        val pitchClass = ((p % 12) + 12) % 12

        // 1. 强制消除非自然半音（就近修正到自然音）
        if (pitchClass !in NATURAL_NOTES) {
            val downClass = ((pitchClass - 1) % 12 + 12) % 12
            p = if (downClass in NATURAL_NOTES) p - 1 else p + 1
        }

        // 2. 按功能区折叠八度
        if (isMelody) {
            while (p < 57) p += 12
            while (p > 72) p -= 12
        } else {
            while (p < 48) p += 12
            while (p > 60) p -= 12
        }

        // 3. 兜底匹配到 15 键最接近的值
        var bestKey = 0
        var minDiff = Int.MAX_VALUE
        for (i in SKY_KEYS.indices) {
            val diff = Math.abs(p - SKY_KEYS[i])
            if (diff < minDiff) {
                minDiff = diff
                bestKey = i
                if (diff == 0) break
            }
        }
        return bestKey
    }

    /**
     * 兼容方法：默认按旋律区将音高折叠映射为 0..14 键位
     */
    fun foldPitchToSkyKey(pitch: Int): Int {
        return fitToSkyKey(pitch, isMelody = true)
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
}
