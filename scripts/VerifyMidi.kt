package com.skymusic.player.parser

import java.io.File

fun main() {
    println("==================================================")
    println("      Kotlin MidiParser V7 算法对比验证测试        ")
    println("==================================================")

    val midiFiles = listOf("起风了.mid", "半壶纱.mid", "鸳鸯戏.mid")

    for (fileName in midiFiles) {
        val file = File(fileName)
        if (!file.exists()) {
            println("[ERROR] 文件不存在: $fileName")
            continue
        }

        println("\n>>> 测试文件: ${file.name} <<<")
        val cleanName = file.nameWithoutExtension
        val song = file.inputStream().use { stream ->
            MidiParser.parse(stream, cleanName)
        }

        println("歌曲标题 (title)  : ${song.title}")
        println("乐谱艺术家/调性   : ${song.artist}")
        println("乐谱 BPM         : ${song.bpm}")
        println("打击事件总数      : ${song.notes.size}")
        println("总触控音符数      : ${song.noteCount}")
        println("曲目时长         : ${song.getFormattedDuration()} (${song.durationMs} ms)")

        if (song.notes.isNotEmpty()) {
            val first5 = song.notes.take(5).map { "t=${it.timeMs}ms:keys=${it.keys}" }
            println("前5个事件        : $first5")
        }

        // 验证标题未被英文或乱码覆盖
        if (song.title != cleanName) {
            println("[FAILED] 标题不匹配! 期望: $cleanName, 实际: ${song.title}")
        } else {
            println("[PASSED] 导入曲目名称与原文件名一致: ${song.title}")
        }
    }
    println("\n==================================================")
    println("                  验证完成！                      ")
    println("==================================================")
}
