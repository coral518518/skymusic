package com.skymusic.player.engine

import com.skymusic.player.model.NoteEvent
import com.skymusic.player.model.Song
import kotlinx.coroutines.*
import java.util.concurrent.atomic.AtomicBoolean

enum class PlayState {
    IDLE,
    PLAYING,
    PAUSED,
    COMPLETED
}

class PlayEngine {

    interface PlaybackListener {
        fun onNoteTriggered(keys: List<Int>)
        fun onProgressUpdate(currentMs: Long, totalMs: Long, progressPercent: Float)
        fun onStateChanged(state: PlayState)
        fun onSongCompleted()
    }

    var listener: PlaybackListener? = null

    var currentSong: Song? = null
        private set

    var state: PlayState = PlayState.IDLE
        private set(value) {
            field = value
            listener?.onStateChanged(value)
        }

    var speed: Float = 1.0f
        set(value) {
            field = value.coerceIn(0.25f, 2.5f)
        }

    var transpose: Int = 0 // 键盘半音/移调偏移 (-7 到 +7)

    private var playbackJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    private var currentSongPositionMs = 0L
    private var isSeeking = AtomicBoolean(false)

    fun loadSong(song: Song) {
        stop()
        currentSong = song
        currentSongPositionMs = 0L
        state = PlayState.IDLE
        listener?.onProgressUpdate(0L, song.durationMs, 0f)
    }

    fun play() {
        val song = currentSong ?: return
        if (state == PlayState.PLAYING) return

        state = PlayState.PLAYING
        startPlaybackLoop(song)
    }

    fun pause() {
        if (state != PlayState.PLAYING) return
        playbackJob?.cancel()
        state = PlayState.PAUSED
    }

    fun resume() {
        if (state == PlayState.PAUSED) {
            play()
        }
    }

    fun stop() {
        playbackJob?.cancel()
        currentSongPositionMs = 0L
        state = PlayState.IDLE
        currentSong?.let {
            listener?.onProgressUpdate(0L, it.durationMs, 0f)
        }
    }

    fun seekTo(positionMs: Long) {
        val song = currentSong ?: return
        isSeeking.set(true)
        val wasPlaying = (state == PlayState.PLAYING)
        if (wasPlaying) {
            playbackJob?.cancel()
        }

        currentSongPositionMs = positionMs.coerceIn(0L, song.durationMs)
        val progress = if (song.durationMs > 0) currentSongPositionMs.toFloat() / song.durationMs else 0f
        listener?.onProgressUpdate(currentSongPositionMs, song.durationMs, progress)

        isSeeking.set(false)
        if (wasPlaying) {
            startPlaybackLoop(song)
        }
    }

    private fun startPlaybackLoop(song: Song) {
        playbackJob?.cancel()
        playbackJob = scope.launch {
            val notes = song.notes
            if (notes.isEmpty()) {
                state = PlayState.COMPLETED
                listener?.onSongCompleted()
                return@launch
            }

            // 寻找当前进度之后的下一个音符索引
            var nextNoteIndex = notes.indexOfFirst { it.timeMs >= currentSongPositionMs }
            if (nextNoteIndex == -1) {
                // 已经到达末尾
                currentSongPositionMs = song.durationMs
                state = PlayState.COMPLETED
                listener?.onSongCompleted()
                return@launch
            }

            var lastRealTime = System.currentTimeMillis()

            while (isActive && nextNoteIndex < notes.size && state == PlayState.PLAYING) {
                val note = notes[nextNoteIndex]
                val targetSongTime = note.timeMs

                // 计算当前需要等待的时长（根据倍速换算）
                val songDelta = targetSongTime - currentSongPositionMs
                if (songDelta > 0) {
                    val realWaitMs = (songDelta / speed).toLong()
                    if (realWaitMs > 0) {
                        delay(realWaitMs)
                    }
                }

                if (!isActive || state != PlayState.PLAYING) break

                // 更新当前进度时间
                currentSongPositionMs = targetSongTime
                val progress = if (song.durationMs > 0) currentSongPositionMs.toFloat() / song.durationMs else 0f
                listener?.onProgressUpdate(currentSongPositionMs, song.durationMs, progress)

                // 触发按键（应用移调偏移）
                val transposedKeys = note.keys.mapNotNull { key ->
                    val shifted = key + transpose
                    if (shifted in 0..14) shifted else null
                }

                if (transposedKeys.isNotEmpty()) {
                    listener?.onNoteTriggered(transposedKeys)
                }

                nextNoteIndex++
            }

            if (isActive && state == PlayState.PLAYING && nextNoteIndex >= notes.size) {
                // 等待尾音结束
                delay(800)
                currentSongPositionMs = song.durationMs
                listener?.onProgressUpdate(song.durationMs, song.durationMs, 1.0f)
                state = PlayState.COMPLETED
                listener?.onSongCompleted()
            }
        }
    }

    fun release() {
        stop()
        scope.cancel()
    }
}
