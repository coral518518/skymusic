package com.skymusic.player.parser

import android.content.Context
import android.net.Uri
import com.skymusic.player.model.Song
import java.io.InputStream

object SheetImporter {

    /**
     * 根据输入流和文件名智能识别文件类型并完成解析
     */
    fun importFromStream(inputStream: InputStream, filename: String): Song {
        val cleanTitle = cleanFileName(filename)
        val lowerName = filename.lowercase()

        return when {
            lowerName.endsWith(".mid") || lowerName.endsWith(".midi") -> {
                MidiParser.parse(inputStream, cleanTitle)
            }
            lowerName.endsWith(".json") -> {
                val content = inputStream.bufferedReader().use { it.readText() }
                OnlineScoreParser.parse(content, cleanTitle)
            }
            else -> {
                val content = inputStream.bufferedReader().use { it.readText() }
                val trimmed = content.trim()
                if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
                    OnlineScoreParser.parse(trimmed, cleanTitle)
                } else {
                    JianpuParser.parse(trimmed, cleanTitle)
                }
            }
        }
    }

    private fun cleanFileName(filename: String): String {
        var clean = filename.trim()
        try {
            if (clean.contains("%")) {
                clean = java.net.URLDecoder.decode(clean, "UTF-8")
            }
        } catch (e: Exception) {}
        clean = clean.substringAfterLast("/").substringAfterLast("\\")
        if (clean.contains(".")) {
            clean = clean.substringBeforeLast(".")
        }
        return clean.ifBlank { "导入乐谱" }
    }

    fun importFromUri(context: Context, uri: Uri, filename: String): Song? {
        return try {
            context.contentResolver.openInputStream(uri)?.use { stream ->
                importFromStream(stream, filename)
            }
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    /**
     * 直接从本地文件解析并导入乐谱
     */
    fun importFromFile(file: java.io.File): Song? {
        return try {
            if (!file.exists() || !file.isFile) return null
            file.inputStream().use { stream ->
                importFromStream(stream, file.name)
            }
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
}
