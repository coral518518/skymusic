package com.skymusic.player.parser

import java.io.File
import kotlin.math.abs

fun main() {
    val fPreview = File("sky_preview_v7.mid")
    val songPreview = fPreview.inputStream().use { stream ->
        MidiParser.parse(stream, "sky_preview_v7")
    }

    val fRaw = File("半壶纱.mid")
    val songRaw = fRaw.inputStream().use { stream ->
        MidiParser.parse(stream, "半壶纱")
    }

    println("Preview notes count: ${songPreview.notes.size}, duration: ${songPreview.durationMs}, bpm: ${songPreview.bpm}")
    println("Raw parsed notes count: ${songRaw.notes.size}, duration: ${songRaw.durationMs}, bpm: ${songRaw.bpm}")

    var diffCount = 0
    val maxLen = maxOf(songPreview.notes.size, songRaw.notes.size)
    for (i in 0 until maxLen) {
        val nPrev = songPreview.notes.getOrNull(i)
        val nRaw = songRaw.notes.getOrNull(i)
        if (nPrev == null || nRaw == null) {
            println("Diff at $i: preview=$nPrev vs raw=$nRaw")
            diffCount++
            continue
        }
        val timeDiff = abs(nPrev.timeMs - nRaw.timeMs)
        val keysDiff = nPrev.keys != nRaw.keys
        if (keysDiff || timeDiff > 5) {
            println("Diff at $i: preview(t=${nPrev.timeMs}, k=${nPrev.keys}) vs raw(t=${nRaw.timeMs}, k=${nRaw.keys}) [timeDiff=${timeDiff}]")
            diffCount++
            if (diffCount > 25) break
        }
    }
    println("Total differences between sky_preview_v7.mid and raw 半壶纱.mid: $diffCount")

    File("scripts/kt_events.txt").printWriter().use { out ->
        for (note in songRaw.notes) {
            out.println("${note.timeMs},${note.keys.joinToString(";")}")
        }
    }
    println("Updated scripts/kt_events.txt with ${songRaw.notes.size} events.")
}


