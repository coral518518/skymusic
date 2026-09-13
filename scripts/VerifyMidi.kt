package com.skymusic.player.parser

import java.io.File

fun main() {
    val file = File("半壶纱.mid")
    val song = file.inputStream().use { stream ->
        MidiParser.parse(stream, "半壶纱")
    }

    File("scripts/kt_events.txt").printWriter().use { out ->
        for (note in song.notes) {
            out.println("${note.timeMs},${note.keys.joinToString(";")}")
        }
    }
    println("Saved scripts/kt_events.txt, count: ${song.notes.size}, noteCount: ${song.noteCount}")
}
