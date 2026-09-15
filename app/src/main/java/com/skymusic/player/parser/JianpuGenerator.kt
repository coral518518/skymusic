package com.skymusic.player.parser

import android.os.Environment
import android.util.Log
import com.skymusic.player.model.Song
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStreamWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 光遇 15 键标准简谱生成器与文件归档器
 * 核心算法复现音游伴侣网页端 16 分音符时间网格量化与首调大调唱名映射
 */
object JianpuGenerator {

    private const val TAG = "JianpuGenerator"

    // 15 键简谱唱名映射：0~6 -> 1~7; 7~13 -> 1'~7'; 14 -> 1''
    private val DEGREE_NAMES = arrayOf("1", "2", "3", "4", "5", "6", "7")
    private val KEY_TAGS = arrayOf(
        "A1", "A2", "A3", "A4", "A5",
        "B1", "B2", "B3", "B4", "B5",
        "C1", "C2", "C3", "C4", "C5"
    )

    /**
     * 将键位索引 (0~14) 转换为标准简谱符号
     * @param key 0~14
     * @return 简谱音符 (如 1, 5, 1', 3', 1'')
     */
    fun keyToJianpuSymbol(key: Int): String {
        if (key !in 0..14) return ""
        val degree = DEGREE_NAMES[key % 7]
        val octave = key / 7
        return when (octave) {
            0 -> degree       // 中音区: 1 2 3 4 5 6 7
            1 -> "$degree'"   // 高音区: 1' 2' 3' 4' 5' 6' 7'
            else -> "$degree''" // 倍高音区: 1''
        }
    }

    /**
     * 核心算法：基于音游伴侣前端相同的 16 槽位小节量化算法生成纯文本简谱
     */
    fun generateJianpuText(song: Song): String {
        val bpm = if (song.bpm > 0) song.bpm else 120
        // 一拍毫秒 = 60000 / BPM; 16分音符网格 = 一拍的 1/4
        val slotDurationMs = (60000.0 / bpm) / 4.0

        // 1. 将所有按键量化吸附至网格槽位
        val slotMap = mutableMapOf<Int, MutableSet<Int>>()
        for (event in song.notes) {
            val slotIdx = Math.round(event.timeMs / slotDurationMs).toInt()
            val set = slotMap.getOrPut(slotIdx) { mutableSetOf() }
            set.addAll(event.keys.filter { it in 0..14 })
        }

        val maxSlot = if (slotMap.isNotEmpty()) slotMap.keys.maxOrNull() ?: 0 else 0
        val totalBars = (maxSlot / 16) + 1

        val sb = StringBuilder()
        sb.append("============================================================\n")
        sb.append("          光遇 15 键标准简谱 (音游伴侣网格量化引擎生成)\n")
        sb.append("============================================================\n")
        sb.append("曲目名称: 《${song.title}》\n")
        sb.append("编曲作者: ${song.artist}\n")
        sb.append("演奏速度: $bpm BPM | 节拍: 4/4 拍 | 网格细分: 16分音符 (120ms/槽)\n")
        sb.append("音符总数: ${song.noteCount} 个 | 乐曲时长: ${song.getFormattedDuration()}\n")
        sb.append("生成时间: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date())}\n")
        sb.append("\n")
        sb.append("【琴键与简谱唱名对照】\n")
        sb.append("  第一排 (低/中音): A1(1)  A2(2)  A3(3)  A4(4)  A5(5)\n")
        sb.append("  第二排 (中/高音): B1(6)  B2(7)  B3(1') B4(2') B5(3')\n")
        sb.append("  第三排 (高/倍高): C1(4') C2(5') C3(6') C4(7') C5(1'')\n")
        sb.append("符号说明: '.' = 空拍/延音; 数字带点(') = 高音; [ ] = 和弦同时按压\n")
        sb.append("============================================================\n\n")

        // 2. 按小节排版 (每小节 16 槽位，每 4 槽一拍)
        for (bar in 0 until totalBars) {
            val barNumber = bar + 1
            val barSlots = mutableListOf<String>()

            for (s in 0 until 16) {
                val currentSlot = bar * 16 + s
                val keys = slotMap[currentSlot]?.sorted() ?: emptyList()

                if (keys.isEmpty()) {
                    barSlots.add(".")
                } else if (keys.size == 1) {
                    barSlots.add(keyToJianpuSymbol(keys[0]))
                } else {
                    // 和弦组合
                    val chord = keys.joinToString("") { keyToJianpuSymbol(it) }
                    barSlots.add("[$chord]")
                }
            }

            // 每 4 槽作为一拍加入短间隔，使读谱视距更舒适
            val beat1 = barSlots.subList(0, 4).joinToString(" ")
            val beat2 = barSlots.subList(4, 8).joinToString(" ")
            val beat3 = barSlots.subList(8, 12).joinToString(" ")
            val beat4 = barSlots.subList(12, 16).joinToString(" ")

            sb.append(String.format(Locale.getDefault(), "第 %02d 小节:  %s  |  %s  |  %s  |  %s\n", barNumber, beat1, beat2, beat3, beat4))
        }

        sb.append("\n============================================================\n")
        sb.append("                    简谱生成完毕，祝演奏愉快！\n")
        sb.append("============================================================\n")

        return sb.toString()
    }

    /**
     * 将乐谱自动转换简谱并持久化写入系统的 Download/filesss 目录
     * 同时保存一份格式化简谱 .txt 以及原始 .json
     */
    suspend fun convertAndSaveToFilesss(song: Song, rawJson: String? = null): Result<File> = withContext(Dispatchers.IO) {
        try {
            // 获取手机公有 Download 目录
            val publicDownload = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            val filesssDir = File(publicDownload, "filesss")
            if (!filesssDir.exists()) {
                val created = filesssDir.mkdirs()
                if (!created) {
                    Log.w(TAG, "Failed to create public filesss dir, falling back")
                }
            }

            val sanitizedTitle = song.title.replace(Regex("""[\\/:*?"<>|]"""), "_").trim()
            val textFile = File(filesssDir, "${sanitizedTitle}_简谱.txt")

            // 1. 写入文本简谱
            val jianpuText = generateJianpuText(song)
            OutputStreamWriter(FileOutputStream(textFile), "UTF-8").use {
                it.write(jianpuText)
                it.flush()
            }

            // 2. 若有原版 JSON，也一同同步保存在 filesss 目录，方便备用
            if (!rawJson.isNullOrBlank()) {
                val jsonFile = File(filesssDir, "${sanitizedTitle}.json")
                OutputStreamWriter(FileOutputStream(jsonFile), "UTF-8").use {
                    it.write(rawJson)
                    it.flush()
                }
            }

            Log.i(TAG, "Successfully saved jianpu and json to ${textFile.absolutePath}")
            Result.success(textFile)
        } catch (e: Exception) {
            Log.e(TAG, "Error saving jianpu to filesss directory", e)
            Result.failure(e)
        }
    }
}
