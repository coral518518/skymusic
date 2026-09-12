package com.skymusic.player.parser

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object MidiParser {

    private data class RawMidiNote(
        val tick: Long,
        val noteNumber: Int, // 0..127
        val velocity: Int
    )

    private data class TempoChange(
        val tick: Long,
        val usPerQuarter: Long
    )

    /**
     * 解析标准 MIDI 文件输入流
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
        val format = buffer.short.toInt()
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

                var status = buffer.get().toInt() and 0xFF
                if (status < 0x80) {
                    // Running status
                    status = runningStatus
                    buffer.position(buffer.position() - 1)
                } else {
                    runningStatus = status
                }

                if (status == 0xFF) {
                    // Meta 事件
                    val metaType = buffer.get().toInt() and 0xFF
                    val metaLen = readVariableLength(buffer).toInt()
                    val metaData = ByteArray(metaLen)
                    buffer.get(metaData)

                    when (metaType) {
                        0x03 -> { // Track Name / Song Title
                            val name = String(metaData).trim()
                            if (name.isNotEmpty() && songTitle == defaultTitle) {
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
                    // SysEx 事件，跳过
                    val sysexLen = readVariableLength(buffer).toInt()
                    buffer.position(buffer.position() + sysexLen)
                } else {
                    // 常用 Channel 消息
                    val msgType = status and 0xF0
                    when (msgType) {
                        0x90 -> { // Note On
                            val note = buffer.get().toInt() and 0xFF
                            val vel = buffer.get().toInt() and 0xFF
                            if (vel > 0) {
                                rawNotes.add(RawMidiNote(currentTick, note, vel))
                            }
                        }
                        0x80 -> { // Note Off
                            buffer.get()
                            buffer.get()
                        }
                        0xA0, 0xB0, 0xE0 -> { // 2 字节参数消息
                            buffer.get()
                            buffer.get()
                        }
                        0xC0, 0xD0 -> { // 1 字节参数消息
                            buffer.get()
                        }
                    }
                }
            }

            buffer.position(trackEndPos)
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
            Pair(ms, note.noteNumber)
        }.sortedBy { it.first }

        // 4. 智能调性拟合：寻找最佳半音移调值，让最多音符落入光遇 15 个自然大调音阶
        val optimalTranspose = findBestTranspose(timedNotes.map { it.second })

        // 5. 寻找最佳八度偏移，使得中位数音符落在 C5 (72) 附近
        val shiftedNotes = timedNotes.map { Pair(it.first, it.second + optimalTranspose) }
        val octaveShift = findBestOctaveShift(shiftedNotes.map { it.second })

        // 6. 将 MIDI 音高映射到光遇 15 个键 (0 ~ 14)
        // 并按照 20ms 时间窗融合成和弦
        val timeMap = mutableMapOf<Long, MutableList<Int>>()
        for ((ms, pitch) in shiftedNotes) {
            val finalPitch = pitch + octaveShift
            val keyIndex = midiPitchToSkyKey(finalPitch)
            if (keyIndex in 0..14) {
                // 量化到 15ms 时间片，便于识别并发和弦
                val quantizedTime = (ms / 15L) * 15L
                val keys = timeMap.getOrPut(quantizedTime) { mutableListOf() }
                if (!keys.contains(keyIndex)) {
                    keys.add(keyIndex)
                }
            }
        }

        val noteEvents = mutableListOf<NoteEvent>()
        for ((time, keys) in timeMap) {
            noteEvents.add(NoteEvent(timeMs = time, keys = keys.sorted()))
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
     * 自然七声音阶白键半音模数: C=0, D=2, E=4, F=5, G=7, A=9, B=11
     */
    private val DIATONIC_SET = setOf(0, 2, 4, 5, 7, 9, 11)

    /**
     * 寻找最佳移调量 (-6 ~ +6)，使得自然音阶命中率最高
     */
    private fun findBestTranspose(pitches: List<Int>): Int {
        if (pitches.isEmpty()) return 0
        var bestShift = 0
        var maxHits = -1

        for (shift in -6..6) {
            var hits = 0
            for (p in pitches) {
                val mod = ((p + shift) % 12 + 12) % 12
                if (mod in DIATONIC_SET) {
                    hits++
                }
            }
            if (hits > maxHits) {
                maxHits = hits
                bestShift = shift
            }
        }
        return bestShift
    }

    private fun findBestOctaveShift(pitches: List<Int>): Int {
        if (pitches.isEmpty()) return 0
        val sorted = pitches.sorted()
        val median = sorted[sorted.size / 2]
        // 目标中位数中心：C5 (MIDI 72)
        val diff = 72 - median
        val octaves = Math.round(diff / 12.0f) * 12
        return octaves.coerceIn(-24, 24)
    }

    /**
     * 光遇标准 15 键对应的标准 MIDI 音高（Key of C）：
     * Key 0: C4 (60)
     * Key 1: D4 (62)
     * Key 2: E4 (64)
     * Key 3: F4 (65)
     * Key 4: G4 (67)
     * Key 5: A4 (69)
     * Key 6: B4 (71)
     * Key 7: C5 (72)
     * Key 8: D5 (74)
     * Key 9: E5 (76)
     * Key 10: F5 (77)
     * Key 11: G5 (79)
     * Key 12: A5 (81)
     * Key 13: B5 (83)
     * Key 14: C6 (84)
     */
    private val SKY_KEY_PITCHES = intArrayOf(
        60, 62, 64, 65, 67, 69, 71, // 0..6
        72, 74, 76, 77, 79, 81, 83, // 7..13
        84                          // 14
    )

    fun midiPitchToSkyKey(pitch: Int): Int {
        // 如果正好落在范围内，直接查找或就近匹配
        if (pitch <= SKY_KEY_PITCHES.first()) return 0
        if (pitch >= SKY_KEY_PITCHES.last()) return 14

        var bestKey = 0
        var minDiff = Int.MAX_VALUE
        for (i in SKY_KEY_PITCHES.indices) {
            val diff = Math.abs(pitch - SKY_KEY_PITCHES[i])
            if (diff < minDiff) {
                minDiff = diff
                bestKey = i
            }
        }
        return bestKey
    }
}
