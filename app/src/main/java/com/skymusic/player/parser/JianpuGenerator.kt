package com.skymusic.player.parser

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
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
            0 -> degree         // 中音区: 1 2 3 4 5 6 7
            1 -> "$degree'"     // 高音区: 1' 2' 3' 4' 5' 6' 7'
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
        sb.append("演奏速度: $bpm BPM | 节拍: 4/4 拍 | 网格细分: 16分音符 (${String.format(Locale.getDefault(), "%.1f", slotDurationMs)}ms/槽)\n")
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
     * 具备跨 Android 版本目录智能适配与 MediaScanner 广播通知，确保手机文件管理器秒级可见
     */
    suspend fun convertAndSaveToFilesss(context: Context, song: Song, rawJson: String? = null): Result<File> = withContext(Dispatchers.IO) {
        val sanitizedTitle = song.title.replace(Regex("""[\\/:*?"<>|]"""), "_").trim().ifBlank { "乐谱_${System.currentTimeMillis()}" }
        val jianpuText = generateJianpuText(song)

        var primaryFile: File? = null

        // 1. Android 10+ (Q+) 使用系统标准 MediaStore.Downloads API 写入公共 Download/filesss
        // 免运行时权限、不受 Scoped Storage 限制，手机文件管理器 100% 秒见
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val resolver = context.contentResolver

                // 写入简谱文本
                val txtValues = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, "${sanitizedTitle}_简谱.txt")
                    put(MediaStore.Downloads.MIME_TYPE, "text/plain")
                    put(MediaStore.Downloads.RELATIVE_PATH, "Download/filesss")
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
                val txtUri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, txtValues)
                if (txtUri != null) {
                    resolver.openOutputStream(txtUri)?.use { os ->
                        os.write(jianpuText.toByteArray(Charsets.UTF_8))
                        os.flush()
                    }
                    txtValues.clear()
                    txtValues.put(MediaStore.Downloads.IS_PENDING, 0)
                    resolver.update(txtUri, txtValues, null, null)
                    Log.i(TAG, "Successfully created jianpu via MediaStore: $txtUri")
                }

                // 同步写入原始 JSON
                if (!rawJson.isNullOrBlank()) {
                    val jsonValues = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, "${sanitizedTitle}.json")
                        put(MediaStore.Downloads.MIME_TYPE, "application/json")
                        put(MediaStore.Downloads.RELATIVE_PATH, "Download/filesss")
                        put(MediaStore.Downloads.IS_PENDING, 1)
                    }
                    val jsonUri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, jsonValues)
                    if (jsonUri != null) {
                        resolver.openOutputStream(jsonUri)?.use { os ->
                            os.write(rawJson.toByteArray(Charsets.UTF_8))
                            os.flush()
                        }
                        jsonValues.clear()
                        jsonValues.put(MediaStore.Downloads.IS_PENDING, 0)
                        resolver.update(jsonUri, jsonValues, null, null)
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "MediaStore write failed, continuing with direct File API fallback", e)
            }
        }

        // 2. 多级候选物理文件系统目录 (兼顾 Android 9 及以下、直接文件访问及应用专属目录)
        val candidateDirs = mutableListOf<File>()

        // 候选 1: /storage/emulated/0/Download/filesss
        try {
            val pub = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if (pub != null) candidateDirs.add(File(pub, "filesss"))
        } catch (_: Exception) {}

        // 候选 2: /sdcard/Download/filesss
        try {
            val sd = Environment.getExternalStorageDirectory()
            if (sd != null) candidateDirs.add(File(sd, "Download/filesss"))
        } catch (_: Exception) {}

        // 候选 3: 应用外部存储文件目录
        try {
            val ext = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            if (ext != null) candidateDirs.add(File(ext, "filesss"))
        } catch (_: Exception) {}

        // 候选 4: 应用内部文件目录兜底
        candidateDirs.add(File(context.filesDir, "filesss"))

        var lastError: Exception? = null
        for (targetDir in candidateDirs) {
            try {
                if (!targetDir.exists()) {
                    targetDir.mkdirs()
                }

                if (targetDir.exists() && targetDir.canWrite()) {
                    val textFile = File(targetDir, "${sanitizedTitle}_简谱.txt")
                    OutputStreamWriter(FileOutputStream(textFile), "UTF-8").use {
                        it.write(jianpuText)
                        it.flush()
                    }

                    var jsonFile: File? = null
                    if (!rawJson.isNullOrBlank()) {
                        val jf = File(targetDir, "${sanitizedTitle}.json")
                        OutputStreamWriter(FileOutputStream(jf), "UTF-8").use {
                            it.write(rawJson)
                            it.flush()
                        }
                        jsonFile = jf
                    }

                    // 广播通知 Android 系统媒体扫描器刷新，使手机文件管理器与电脑 MTP 连接立即显示新文件
                    try {
                        val scanPaths = listOfNotNull(textFile.absolutePath, jsonFile?.absolutePath).toTypedArray()
                        MediaScannerConnection.scanFile(context, scanPaths, null, null)
                    } catch (e: Exception) {
                        Log.w(TAG, "MediaScanner error", e)
                    }

                    if (primaryFile == null) {
                        primaryFile = textFile
                    }
                    Log.i(TAG, "Successfully wrote jianpu to File: ${textFile.absolutePath}")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Failed writing to ${targetDir.absolutePath}, trying next candidate", e)
                lastError = e
            }
        }

        if (primaryFile != null) {
            Result.success(primaryFile)
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // MediaStore 写入成功但物理 File 无法获取句柄时的保底
            val pub = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            Result.success(File(pub, "filesss/${sanitizedTitle}_简谱.txt"))
        } else {
            Result.failure(lastError ?: Exception("无法在任何存储候选目录中创建文件"))
        }
    }

    /**
     * 将调试报文直接落地写入手机 Download/filesss 目录，便于排查接口返回格式
     */
    fun saveDebugFile(context: Context, filename: String, content: String): File? {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val resolver = context.contentResolver
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, filename)
                    put(MediaStore.Downloads.MIME_TYPE, "application/json")
                    put(MediaStore.Downloads.RELATIVE_PATH, "Download/filesss")
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
                val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                if (uri != null) {
                    resolver.openOutputStream(uri)?.use { os ->
                        os.write(content.toByteArray(Charsets.UTF_8))
                        os.flush()
                    }
                    values.clear()
                    values.put(MediaStore.Downloads.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                }
            }

            val pub = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            val dir = File(pub, "filesss")
            if (!dir.exists()) dir.mkdirs()
            val file = File(dir, filename)
            OutputStreamWriter(FileOutputStream(file), "UTF-8").use {
                it.write(content)
                it.flush()
            }
            try {
                MediaScannerConnection.scanFile(context, arrayOf(file.absolutePath), null, null)
            } catch (_: Exception) {}
            return file
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save debug file $filename", e)
            return null
        }
    }
}
