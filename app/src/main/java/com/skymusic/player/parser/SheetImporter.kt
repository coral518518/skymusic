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
        val lowerName = filename.lowercase()

        return when {
            lowerName.endsWith(".mid") || lowerName.endsWith(".midi") -> {
                val cleanTitle = filename.substringBeforeLast(".")
                MidiParser.parse(inputStream, cleanTitle)
            }
            lowerName.endsWith(".json") -> {
                val content = inputStream.bufferedReader().use { it.readText() }
                val cleanTitle = filename.substringBeforeLast(".")
                SkyJsonParser.parse(content, cleanTitle)
            }
            else -> {
                val content = inputStream.bufferedReader().use { it.readText() }
                val trimmed = content.trim()
                val cleanTitle = filename.substringBeforeLast(".")
                if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
                    SkyJsonParser.parse(trimmed, cleanTitle)
                } else {
                    JianpuParser.parse(trimmed, cleanTitle)
                }
            }
        }
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
}
