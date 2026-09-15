package com.skymusic.player.parser

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
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

    data class LocalScoreInfo(
        val title: String,
        val jsonContent: String,
        val jsonFile: File? = null,
        val jianpuFile: File? = null
    )

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

    fun sanitizeFileName(title: String): String =
        title.replace(Regex("""[\\/:*?"<>|]"""), "_").trim().ifBlank { "乐谱_${System.currentTimeMillis()}" }

    fun getCandidateDirectories(context: Context): List<File> {
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
        return candidateDirs
    }

    fun getCandidateJsonFileNames(context: Context, scoreId: Long, title: String): List<String> {
        val names = LinkedHashSet<String>()
        val sanitized = sanitizeFileName(title)

        // 1. SharedPreferences 历史映射 (按 scoreId 精准对应已下载文件名)
        if (scoreId > 0) {
            try {
                val sp = context.getSharedPreferences("mgm_local_scores", Context.MODE_PRIVATE)
                val mappedName = sp.getString("id_${scoreId}_filename", null)
                if (!mappedName.isNullOrBlank()) {
                    names.add(mappedName)
                }
            } catch (_: Exception) {}
        }

        // 2. 基于标题的标准命名
        if (sanitized.isNotBlank()) {
            names.add("${sanitized}.json")
        }
        val cleanTitle = title.trim()
        if (cleanTitle.isNotBlank() && cleanTitle != sanitized) {
            names.add("${cleanTitle}.json")
        }

        // 3. 基于 ID 和标题组合命名
        if (scoreId > 0) {
            if (sanitized.isNotBlank()) {
                names.add("${sanitized}_${scoreId}.json")
                names.add("${scoreId}_${sanitized}.json")
            }
            names.add("${scoreId}.json")
        }

        return names.toList()
    }

    /**
     * 智能检测并读取本地已保存的乐谱 (优先在系统的 Download/filesss/ 查找)
     * 支持通过 ID 历史映射或歌名模糊匹配，命中了直接返回 JSON 原文，无需重复调用网络下载
     */
    fun findLocalScore(context: Context, scoreId: Long, title: String): LocalScoreInfo? {
        val candidateNames = getCandidateJsonFileNames(context, scoreId, title)
        val sanitized = sanitizeFileName(title)
        val jianpuName = "${sanitized}_简谱.txt"

        // 1. 优先扫描多级物理候选目录
        for (dir in getCandidateDirectories(context)) {
            if (!dir.exists() || !dir.isDirectory) continue

            for (jsonName in candidateNames) {
                val jf = File(dir, jsonName)
                if (jf.exists() && jf.isFile && jf.length() > 0) {
                    try {
                        val content = jf.readText(Charsets.UTF_8)
                        if (content.isNotBlank() && content.length > 10) {
                            val tf = File(dir, jianpuName)
                            val finalTf = if (tf.exists() && tf.isFile && tf.length() > 0) tf else null
                            Log.i(TAG, "Found local score in File system: ${jf.absolutePath} (${content.length} chars)")
                            return LocalScoreInfo(
                                title = title,
                                jsonContent = content,
                                jsonFile = jf,
                                jianpuFile = finalTf
                            )
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "Error reading local file: ${jf.absolutePath}", e)
                    }
                }
            }
        }

        // 2. Android 10+ (Q+) 查询 MediaStore.Downloads (兼容 Scoped Storage 沙盒)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val resolver = context.contentResolver
                val projection = arrayOf(
                    MediaStore.Downloads._ID,
                    MediaStore.Downloads.DISPLAY_NAME,
                    MediaStore.Downloads.RELATIVE_PATH
                )
                val selection = "${MediaStore.Downloads.RELATIVE_PATH} LIKE ?"
                val selectionArgs = arrayOf("Download/filesss%")
                resolver.query(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    projection,
                    selection,
                    selectionArgs,
                    null
                )?.use { cursor ->
                    val idCol = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                    val nameCol = cursor.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)

                    var matchedUri: android.net.Uri? = null
                    var matchedName: String? = null

                    while (cursor.moveToNext()) {
                        val displayName = cursor.getString(nameCol) ?: continue
                        val isMatch = candidateNames.any { it.equals(displayName, ignoreCase = true) }
                        if (isMatch) {
                            val docId = cursor.getLong(idCol)
                            matchedUri = ContentUris.withAppendedId(
                                MediaStore.Downloads.EXTERNAL_CONTENT_URI, docId
                            )
                            matchedName = displayName
                            break
                        }
                    }

                    if (matchedUri != null) {
                        val content = resolver.openInputStream(matchedUri)?.bufferedReader(Charsets.UTF_8)?.use {
                            it.readText()
                        }
                        if (!content.isNullOrBlank() && content.length > 10) {
                            Log.i(TAG, "Found local score in MediaStore: $matchedName ($matchedUri)")
                            return LocalScoreInfo(
                                title = title,
                                jsonContent = content,
                                jsonFile = null,
                                jianpuFile = null
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error querying MediaStore for local score", e)
            }
        }

        return null
    }

    /**
     * 极速判断本地是否已存在该曲谱的缓存文件 (用于列表渲染与状态徽章)
     */
    fun isScoreCachedLocally(context: Context, scoreId: Long, title: String): Boolean {
        val candidateNames = getCandidateJsonFileNames(context, scoreId, title)
        for (dir in getCandidateDirectories(context)) {
            if (!dir.exists() || !dir.isDirectory) continue
            for (name in candidateNames) {
                val f = File(dir, name)
                if (f.exists() && f.length() > 0) return true
            }
        }
        if (scoreId > 0) {
            try {
                val sp = context.getSharedPreferences("mgm_local_scores", Context.MODE_PRIVATE)
                val mapped = sp.getString("id_${scoreId}_filename", null)
                if (!mapped.isNullOrBlank()) {
                    for (dir in getCandidateDirectories(context)) {
                        val f = File(dir, mapped)
                        if (f.exists() && f.length() > 0) return true
                    }
                }
            } catch (_: Exception) {}
        }
        return false
    }

    /**
     * 将乐谱自动转换简谱并持久化写入系统的 Download/filesss 目录
     * 具备跨 Android 版本目录智能适配与 MediaScanner 广播通知，确保手机文件管理器秒级可见
     */
    suspend fun convertAndSaveToFilesss(
        context: Context,
        song: Song,
        rawJson: String? = null,
        scoreId: Long = -1L
    ): Result<File> = withContext(Dispatchers.IO) {
        val sanitizedTitle = sanitizeFileName(song.title)
        val jianpuText = generateJianpuText(song)

        // 记录 ID 到文件名的持久化映射
        if (scoreId > 0) {
            try {
                val sp = context.getSharedPreferences("mgm_local_scores", Context.MODE_PRIVATE)
                sp.edit()
                    .putString("id_${scoreId}_title", song.title)
                    .putString("id_${scoreId}_filename", "${sanitizedTitle}.json")
                    .putLong("id_${scoreId}_time", System.currentTimeMillis())
                    .apply()
            } catch (e: Exception) {
                Log.w(TAG, "Failed to save local score id mapping", e)
            }
        }

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
        val candidateDirs = getCandidateDirectories(context)

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
     * 将调试报文直接落地写入手机 Download/filesss 目录（直接原地覆盖，不执行删除操作）
     */
    fun saveDebugFile(context: Context, filename: String, content: String): File? {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val resolver = context.contentResolver
                val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI

                // 1. 查询 MediaStore 中是否已经存在该文件
                val projection = arrayOf(MediaStore.Downloads._ID)
                val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ? AND ${MediaStore.Downloads.RELATIVE_PATH} LIKE ?"
                val selectionArgs = arrayOf(filename, "Download/filesss%")
                
                var targetUri: Uri? = null
                resolver.query(collection, projection, selection, selectionArgs, null)?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                        val id = cursor.getLong(idColumn)
                        targetUri = ContentUris.withAppendedId(collection, id)
                    }
                }

                // 2. 如果不存在才新建（insert）；如果已存在则直接复用 targetUri
                if (targetUri == null) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, filename)
                        put(MediaStore.Downloads.MIME_TYPE, "application/json")
                        put(MediaStore.Downloads.RELATIVE_PATH, "Download/filesss")
                    }
                    targetUri = resolver.insert(collection, values)
                }

                // 3. 原地覆盖写入内容（"rwt" 模式：清空现有内容重新写入，不破坏原有文件结构）
                if (targetUri != null) {
                    resolver.openOutputStream(targetUri!!, "rwt")?.use { os ->
                        os.write(content.toByteArray(Charsets.UTF_8))
                        os.flush()
                    }
                }

                // 4. 返回对应的 File 句柄，注意这里直接 return，避免往下走造成二次写入
                val pub = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                return File(File(pub, "filesss"), filename)
            } else {
                // Android 9 及以下走传统 File 覆盖写入
                val pub = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                val dir = File(pub, "filesss")
                if (!dir.exists()) dir.mkdirs()
                val file = File(dir, filename)

                FileOutputStream(file, false).use { fos ->
                    fos.write(content.toByteArray(Charsets.UTF_8))
                    fos.flush()
                }

                try {
                    MediaScannerConnection.scanFile(context, arrayOf(file.absolutePath), null, null)
                } catch (_: Exception) {}

                return file
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save debug file $filename", e)
            return null
        }
    }
}
