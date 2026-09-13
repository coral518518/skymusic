package com.skymusic.player.parser

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object MidiParser {

    private data class RawNote(
        val pitch: Int,
        val startTick: Long,
        val durTicks: Long,
        val channel: Int
    )

    private data class TempoChange(
        val tick: Long,
        val usPerQuarter: Long
    )

    // 自然大调半音阶步长 (全全半全全全半)
    val MAJOR_STEPS = intArrayOf(0, 2, 4, 5, 7, 9, 11)

    // 光遇 15 键对应的“首调音级”规范 (从0开始索引)
    // 键位 0~6:  低音 1, 2, 3, 4, 5, 6, 7 (对应 A1 ~ B2)
    // 键位 7~13: 中音 1, 2, 3, 4, 5, 6, 7 (对应 B3 ~ C4)
    // 键位 14:   高音 1 (对应 C5)
    val SKY_PITCH_MAP = intArrayOf(
        48, 50, 52, 53, 55, 57, 59, // 0~6:  低音组
        60, 62, 64, 65, 67, 69, 71, // 7~13: 中音组
        72                          // 14:   高音 1
    )

    val SKY_KEY_PITCHES = SKY_PITCH_MAP

    /**
     * 解析标准 MIDI 文件输入流并基于“首调简谱”核心乐理重构转写为光遇 15 键乐谱
     * 自动检测自然大调主音 Tonic，执行音区自适应安全下沉，并抽取旋律高音与伴奏最低根音（防砸琴骨架）
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

        if (headerSize > 6) {
            buffer.position(buffer.position() + (headerSize - 6))
        }

        val allNotes = mutableListOf<RawNote>()
        val tempoChanges = mutableListOf<TempoChange>()
        tempoChanges.add(TempoChange(0L, 500_000L)) // 默认 120 BPM = 500,000 微秒/拍

        var songTitle = defaultTitle

        // 2. 逐音轨提取有效音符（剔除 Channel 9 打击乐/鼓点）
        for (t in 0 until numTracks) {
            if (buffer.remaining() < 8) break
            val trackId = ByteArray(4)
            buffer.get(trackId)
            val trackLength = buffer.int
            val trackEndPos = buffer.position() + trackLength

            var currentTick = 0L
            var runningStatus = 0
            val activeNotes = mutableMapOf<Pair<Int, Int>, Long>() // (channel, note) -> startTick

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
                                if (channel != 9) {
                                    val key = Pair(channel, note)
                                    if (vel > 0) {
                                        val prev = activeNotes[key]
                                        if (prev != null) {
                                            val dur = (currentTick - prev).coerceAtLeast(1L)
                                            allNotes.add(RawNote(note, prev, dur, channel))
                                        }
                                        activeNotes[key] = currentTick
                                    } else {
                                        val prev = activeNotes.remove(key)
                                        if (prev != null) {
                                            val dur = (currentTick - prev).coerceAtLeast(1L)
                                            allNotes.add(RawNote(note, prev, dur, channel))
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
                                    val prev = activeNotes.remove(key)
                                    if (prev != null) {
                                        val dur = (currentTick - prev).coerceAtLeast(1L)
                                        allNotes.add(RawNote(note, prev, dur, channel))
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

            for ((key, startTick) in activeNotes) {
                allNotes.add(RawNote(key.second, startTick, ppq.toLong(), key.first))
            }

            buffer.position(trackEndPos.coerceAtMost(buffer.limit()))
        }

        if (allNotes.isEmpty()) {
            return Song(
                id = UUID.randomUUID().toString(),
                title = songTitle,
                artist = "首调简谱转换",
                bpm = 120,
                notes = emptyList(),
                durationMs = 0L,
                type = "MIDI"
            )
        }

        // 3. 首调根音识别（通过音阶统计与大调主三和弦 1, 3, 5 权重锁定最佳 Tonic）
        val tonic = detectTonicRoot(allNotes)

        // 4. 旋律高度评估与全局八度自适应（若全曲平均音高高于中音 G (65)，下沉一个八度避免高音爆框）
        val avgPitch = allNotes.map { it.pitch }.average()
        val octaveShift = if (avgPitch > 65.0) -1 else 0

        // 5. 时间网格与和弦骨架提取（防砸琴：同拍 32 分音符容差内，必定保留最高音主旋律；伴奏只保留最低音根音）
        allNotes.sortWith(compareBy<RawNote> { it.startTick }.thenByDescending { it.pitch })
        val timeThreshold = (ppq / 8).coerceAtLeast(1)

        tempoChanges.sortBy { it.tick }
        val timeMap = mutableMapOf<Long, MutableList<Int>>()

        var i = 0
        while (i < allNotes.size) {
            val curTick = allNotes[i].startTick
            val cluster = mutableListOf<RawNote>()
            while (i < allNotes.size && (allNotes[i].startTick - curTick) <= timeThreshold) {
                cluster.add(allNotes[i])
                i++
            }

            val selected = mutableListOf<RawNote>()
            selected.add(cluster.first()) // 最高音主旋律
            if (cluster.size > 1 && cluster.last().pitch != cluster.first().pitch) {
                selected.add(cluster.last()) // 最低音伴奏根音
            }

            val timeMs = tickToMillis(curTick, ppq, tempoChanges)
            val quantizedTime = Math.round(timeMs / 25.0) * 25L
            val keys = timeMap.getOrPut(quantizedTime) { mutableListOf() }

            for (n in selected) {
                val skyKey = pitchToSkyKey(n.pitch, tonic, octaveShift)
                if (!keys.contains(skyKey)) {
                    keys.add(skyKey)
                }
            }
        }

        val noteEvents = mutableListOf<NoteEvent>()
        for ((time, rawKeys) in timeMap) {
            val distinctSorted = rawKeys.distinct().sorted()
            noteEvents.add(NoteEvent(timeMs = time, keys = distinctSorted))
        }
        noteEvents.sort()

        val duration = if (noteEvents.isNotEmpty()) noteEvents.last().timeMs + 1000L else 0L
        val avgTempoUs = if (tempoChanges.isNotEmpty()) tempoChanges.first().usPerQuarter else 500_000L
        val bpm = (60_000_000L / avgTempoUs).toInt().coerceIn(40, 240)

        return Song(
            id = UUID.randomUUID().toString(),
            title = songTitle,
            artist = "首调简谱转换",
            bpm = bpm,
            notes = noteEvents,
            durationMs = duration,
            type = "MIDI"
        )
    }

    /**
     * 通过统计音级权重与三和弦探测，寻找最契合自然大调的主音 Tonic (0~11)
     */
    fun detectTonicRoot(notes: List<RawNote>): Int {
        val counts = IntArray(12)
        for (n in notes) {
            val pc = ((n.pitch % 12) + 12) % 12
            counts[pc]++
        }

        var bestRoot = 0
        var maxScore = -1.0

        for (candidateRoot in 0 until 12) {
            var inScaleNotes = 0
            for (step in MAJOR_STEPS) {
                val pc = (candidateRoot + step) % 12
                inScaleNotes += counts[pc]
            }

            // 加分项：统计强拍/高频音是否落在大调三和弦 (1, 3, 5) 上
            val triadBonus = (counts[candidateRoot] +
                    counts[(candidateRoot + 4) % 12] +
                    counts[(candidateRoot + 7) % 12]) * 0.5

            val totalScore = inScaleNotes + triadBonus
            if (totalScore > maxScore) {
                maxScore = totalScore
                bestRoot = candidateRoot
            }
        }
        return bestRoot
    }

    const val SKY_BASE_PITCH = 48 // C3 作为低音 1 (Do)

    /**
     * 核心乐理映射：将绝对音高转为光遇首调简谱键位 (0~14)
     */
    fun pitchToSkyKey(pitch: Int, root: Int, octaveShift: Int = 0): Int {
        // 相对光遇低音组基准 (C3=48) 与主音的半音差
        val relSemitone = (pitch - (SKY_BASE_PITCH + root)) + (octaveShift * 12)
        val octave = Math.floorDiv(relSemitone, 12)
        val semiInOctave = Math.floorMod(relSemitone, 12)

        // 映射到简谱音级 (1~7 对应 step 0~6)
        // 遇到黑键(不在大调里的半音)，按导音倾向吸附
        var scaleStep = 0
        var minDiff = Int.MAX_VALUE
        for (s in MAJOR_STEPS.indices) {
            val diff = Math.abs(semiInOctave - MAJOR_STEPS[s])
            if (diff < minDiff) {
                minDiff = diff
                scaleStep = s
                if (diff == 0) break
            }
        }

        // 换算为光遇 15 键索引：低音组从 0 开始 (octave 0: 0~6)，中音组从 7 开始 (octave 1: 7~13)
        var alignedKey = (octave * 7) + scaleStep

        // 边界限制与八度折叠
        while (alignedKey < 0) {
            alignedKey += 7
        }
        while (alignedKey > 14) {
            alignedKey -= 7
        }

        return alignedKey
    }

    fun foldPitchToSkyKey(pitch: Int): Int {
        return pitchToSkyKey(pitch, 0, 0)
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
