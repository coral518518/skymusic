package com.skymusic.player.util

import android.content.Context
import android.util.Log
import com.skymusic.player.model.Song
import com.skymusic.player.parser.OnlineScoreParser

object PresetSongs {

    private const val TAG = "PresetSongs"

    // 内存缓存，避免频繁读取 assets I/O
    private var cachedPresetSongs: List<Song>? = null

    /**
     * 获取内置曲库列表
     * 自动从打包的 assets/preset_scores/ 目录中动态读取并解析所有由「音游伴侣」归档的 JSON 乐谱
     */
    fun getPresetList(context: Context? = null): List<Song> {
        cachedPresetSongs?.let {
            if (it.isNotEmpty()) return it
        }

        if (context == null) {
            return cachedPresetSongs ?: emptyList()
        }

        val loadedSongs = mutableListOf<Song>()
        val assetDirs = listOf("preset_scores", "songs")

        for (dir in assetDirs) {
            try {
                val fileNames = context.assets.list(dir) ?: emptyArray()
                val sortedFileNames = fileNames.sorted()

                for (fileName in sortedFileNames) {
                    if (fileName.endsWith(".json", ignoreCase = true)) {
                        try {
                            val jsonString = context.assets.open("$dir/$fileName").bufferedReader(Charsets.UTF_8).use { it.readText() }
                            // 标题推导：如 "32170_偏爱.json" -> "偏爱"
                            val cleanTitle = fileName
                                .removeSuffix(".json")
                                .removeSuffix(".JSON")
                                .replace(Regex("""^\d+_"""), "")
                                .trim()

                            val song = OnlineScoreParser.parse(jsonString, cleanTitle)
                            if (song.notes.isNotEmpty()) {
                                if (loadedSongs.none { it.id == song.id || it.title == song.title }) {
                                    val finalSong = song.copy(
                                        id = "preset_${fileName.removeSuffix(".json")}",
                                        isPreset = true,
                                        type = "音游伴侣"
                                    )
                                    loadedSongs.add(finalSong)
                                    Log.d(TAG, "Loaded preset score: 《${finalSong.title}》 (${finalSong.notes.size} notes, bpm=${finalSong.bpm})")
                                }
                            }
                        } catch (e: Exception) {
                            Log.w(TAG, "Error loading preset score $dir/$fileName", e)
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error listing asset dir: $dir", e)
            }
        }

        cachedPresetSongs = loadedSongs
        Log.i(TAG, "Preset songs loaded total: ${loadedSongs.size} songs")
        return loadedSongs
    }

    /**
     * 清除缓存以支持重新载入
     */
    fun clearCache() {
        cachedPresetSongs = null
    }
}
