package com.skymusic.player.util

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import java.util.UUID

object PresetSongs {

    /**
     * 获取内置示范乐谱列表
     */
    fun getPresetList(): List<Song> {
        return listOf(
            createTwinkleStar(),
            createAlwaysWithMe(),
            createCastleInTheSky(),
            createCanonInD(),
            createWindRises()
        )
    }

    /**
     * 1. 《小星星》 (带和弦伴奏)
     */
    private fun createTwinkleStar(): Song {
        val notes = mutableListOf<NoteEvent>()
        var time = 0L
        val beat = 480L

        // 旋律与和弦映射 (0=1, 1=2, 2=3, 3=4, 4=5, 5=6, 6=7, 7=+1...)
        // (主音, 伴奏低音)
        val score = listOf(
            Pair(listOf(0, 4), "1"), Pair(listOf(0), "1"), Pair(listOf(4, 7), "5"), Pair(listOf(4), "5"),
            Pair(listOf(5, 7), "6"), Pair(listOf(5), "6"), Pair(listOf(4, 0, 2), "5-"), Pair(emptyList<Int>(), ""),
            Pair(listOf(3, 0), "4"), Pair(listOf(3), "4"), Pair(listOf(2, 4), "3"), Pair(listOf(2), "3"),
            Pair(listOf(1, 4), "2"), Pair(listOf(1), "2"), Pair(listOf(0, 2, 4), "1-"), Pair(emptyList<Int>(), ""),

            Pair(listOf(4, 0), "5"), Pair(listOf(4), "5"), Pair(listOf(3, 1), "4"), Pair(listOf(3), "4"),
            Pair(listOf(2, 0), "3"), Pair(listOf(2), "3"), Pair(listOf(1, 4), "2-"), Pair(emptyList<Int>(), ""),
            Pair(listOf(4, 0), "5"), Pair(listOf(4), "5"), Pair(listOf(3, 1), "4"), Pair(listOf(3), "4"),
            Pair(listOf(2, 0), "3"), Pair(listOf(2), "3"), Pair(listOf(1, 4), "2-"), Pair(emptyList<Int>(), ""),

            Pair(listOf(0, 4), "1"), Pair(listOf(0), "1"), Pair(listOf(4, 7), "5"), Pair(listOf(4), "5"),
            Pair(listOf(5, 7), "6"), Pair(listOf(5), "6"), Pair(listOf(4, 0, 2), "5-"), Pair(emptyList<Int>(), ""),
            Pair(listOf(3, 0), "4"), Pair(listOf(3), "4"), Pair(listOf(2, 4), "3"), Pair(listOf(2), "3"),
            Pair(listOf(1, 4), "2"), Pair(listOf(1), "2"), Pair(listOf(0, 4, 7), "1-"), Pair(emptyList<Int>(), "")
        )

        for ((keys, _) in score) {
            if (keys.isNotEmpty()) {
                notes.add(NoteEvent(time, keys))
            }
            time += beat
        }

        return Song(
            id = "preset_twinkle_star",
            title = "小星星 (Twinkle Twinkle Little Star)",
            artist = "经典儿歌 · 和弦版",
            bpm = 125,
            notes = notes,
            durationMs = time + 1000L,
            isPreset = true,
            type = "内置"
        )
    }

    /**
     * 2. 《千与千寻·永远同在》 (Always With Me)
     */
    private fun createAlwaysWithMe(): Song {
        val notes = mutableListOf<NoteEvent>()
        var time = 0L
        val t = 380L

        val melody = listOf(
            // 呼んでいる 胸のどこか奥で
            listOf(2, 0), listOf(3), listOf(4, 0), listOf(2), listOf(0, 4), listOf(7), listOf(6, 1), listOf(4),
            listOf(5, 0), listOf(4), listOf(3, 5), listOf(2), listOf(1, 4), listOf(2), listOf(3, 0), listOf(1),
            // いつも心踊る 夢を見たい
            listOf(2, 0), listOf(3), listOf(4, 0), listOf(7), listOf(8, 1), listOf(7), listOf(6, 4), listOf(5),
            listOf(4, 0), listOf(5), listOf(6, 1), listOf(7), listOf(8, 0, 4), listOf(7), listOf(6), listOf(5),
            // 悲しみは 数えきれないけれど
            listOf(4, 0), listOf(5), listOf(6, 1), listOf(4), listOf(2, 0), listOf(7), listOf(6, 4), listOf(5),
            listOf(4, 0), listOf(3), listOf(2, 4), listOf(1), listOf(0, 2, 4), listOf(4), listOf(7)
        )

        for (keys in melody) {
            notes.add(NoteEvent(time, keys))
            time += t
        }

        return Song(
            id = "preset_always_with_me",
            title = "千与千寻 - 永远同在 (Always With Me)",
            artist = "久石让 (Joe Hisaishi)",
            bpm = 96,
            notes = notes,
            durationMs = time + 1000L,
            isPreset = true,
            type = "内置"
        )
    }

    /**
     * 3. 《天空之城》 (Castle in the Sky)
     */
    private fun createCastleInTheSky(): Song {
        val notes = mutableListOf<NoteEvent>()
        var time = 0L
        val step = 350L

        val intro = listOf(
            listOf(5), listOf(6),
            listOf(7, 0), listOf(6), listOf(7), listOf(9, 2),
            listOf(6, 4), listOf(2), listOf(5),
            listOf(4, 0), listOf(5), listOf(7), listOf(4, 2),
            listOf(2, 0), listOf(1), listOf(2), listOf(3),
            listOf(4, 0), listOf(3), listOf(4), listOf(7, 2),
            listOf(2, 4), listOf(0), listOf(7),
            listOf(6, 1), listOf(7), listOf(8), listOf(7), listOf(6, 1, 4),
            listOf(5, 0), listOf(6), listOf(7, 0, 4)
        )

        for (keys in intro) {
            notes.add(NoteEvent(time, keys))
            time += step
        }

        return Song(
            id = "preset_castle_in_sky",
            title = "天空之城 (Laputa: Castle in the Sky)",
            artist = "久石让",
            bpm = 88,
            notes = notes,
            durationMs = time + 1000L,
            isPreset = true,
            type = "内置"
        )
    }

    /**
     * 4. 《卡农》 (Canon in D)
     */
    private fun createCanonInD(): Song {
        val notes = mutableListOf<NoteEvent>()
        var time = 0L
        val q = 320L

        val canonNotes = listOf(
            // 主题动机与下行低音
            listOf(9, 0), listOf(8), listOf(7, 4), listOf(6),
            listOf(5, 5), listOf(4), listOf(5, 2), listOf(6),
            listOf(7, 0), listOf(8), listOf(9, 4), listOf(8),
            listOf(7, 5), listOf(6), listOf(5, 2), listOf(4),
            // 华彩琶音
            listOf(2, 0), listOf(4), listOf(7), listOf(9),
            listOf(1, 4), listOf(3), listOf(6), listOf(8),
            listOf(0, 5), listOf(2), listOf(5), listOf(7),
            listOf(4, 2), listOf(6), listOf(8), listOf(10),
            listOf(2, 0, 4, 7), listOf(4, 1, 3, 6), listOf(0, 2, 5, 7)
        )

        for (keys in canonNotes) {
            notes.add(NoteEvent(time, keys))
            time += q
        }

        return Song(
            id = "preset_canon_in_d",
            title = "卡农 (Canon in D)",
            artist = "帕赫贝尔 (Pachelbel)",
            bpm = 110,
            notes = notes,
            durationMs = time + 1000L,
            isPreset = true,
            type = "内置"
        )
    }

    /**
     * 5. 《起风了》 (The Wind Rises)
     */
    private fun createWindRises(): Song {
        val notes = mutableListOf<NoteEvent>()
        var time = 0L
        val d = 260L

        val chorus = listOf(
            // 这一路上走走停停
            listOf(4, 0), listOf(5), listOf(7, 2), listOf(7), listOf(7), listOf(6), listOf(7), listOf(8, 4),
            // 顺着少年漂流的痕迹
            listOf(7), listOf(6), listOf(5, 0), listOf(4), listOf(5), listOf(6, 1), listOf(5),
            // 迈出车站的前一刻
            listOf(4, 0), listOf(5), listOf(7, 2), listOf(7), listOf(7), listOf(6), listOf(7), listOf(9, 4),
            // 竟有些犹豫
            listOf(8), listOf(7), listOf(8), listOf(7), listOf(6, 1, 4),
            // 如今走过这世间
            listOf(4, 0), listOf(5), listOf(7, 2), listOf(7), listOf(7), listOf(6), listOf(7), listOf(8, 4),
            // 万般流连
            listOf(9), listOf(8), listOf(7), listOf(6), listOf(7, 0, 4)
        )

        for (keys in chorus) {
            notes.add(NoteEvent(time, keys))
            time += d
        }

        return Song(
            id = "preset_wind_rises",
            title = "起风了 (The Wind Rises)",
            artist = "买辣椒也用券 / 高桥优",
            bpm = 116,
            notes = notes,
            durationMs = time + 1000L,
            isPreset = true,
            type = "内置"
        )
    }
}
