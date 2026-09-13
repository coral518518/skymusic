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
            val newSpeed = value.coerceIn(0.25f, 2.5f)
            if (field != newSpeed) {
                field = newSpeed
                if (state == PlayState.PLAYING) {
                    currentSong?.let { startPlaybackLoop(it) }
                }
            }
        }

    var transpose: Int = 0 // 键盘半音/移调偏移 (-7 到 +7)

    var randomDelayRangeMs: Int = 10 // 两次按键点击之间的随机时间间隔抖动范围 (ms)，防机械式检测

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
                if (currentSongPositionMs >= song.durationMs) {
                    currentSongPositionMs = song.durationMs
                    state = PlayState.COMPLETED
                    listener?.onSongCompleted()
                    return@launch
                }
                nextNoteIndex = notes.size
            }

            // 基于系统单调时钟对齐基准
            val startUptime = android.os.SystemClock.uptimeMillis()
            val startSongMs = currentSongPositionMs

            while (isActive && state == PlayState.PLAYING) {
                val now = android.os.SystemClock.uptimeMillis()
                val elapsedSongMs = ((now - startUptime) * speed).toLong()
                val currentMs = (startSongMs + elapsedSongMs).coerceIn(0L, song.durationMs)
                currentSongPositionMs = currentMs

                // 派发平滑进度更新 (即使在无音符的前奏与休止间奏段，时间轴依然平滑前进，绝不卡死)
                val progress = if (song.durationMs > 0) currentMs.toFloat() / song.durationMs else 0f
                listener?.onProgressUpdate(currentMs, song.durationMs, progress)

                // 触发到达当前时间的所有音符
                while (nextNoteIndex < notes.size && notes[nextNoteIndex].timeMs <= currentMs) {
                    val note = notes[nextNoteIndex]
                    val transposedKeys = note.keys.mapNotNull { key ->
                        val shifted = key + transpose
                        if (shifted in 0..14) shifted else null
                    }
                    if (transposedKeys.isNotEmpty()) {
                        listener?.onNoteTriggered(transposedKeys)
                    }
                    nextNoteIndex++
                }

                // 全部音符播放完毕且时间到达乐曲结尾
                if (nextNoteIndex >= notes.size && currentMs >= song.durationMs) {
                    break
                }

                // 计算下一跳休眠时间：按下一个音符时刻与 25ms 取较小值，保证高帧率平滑进度与精准起音
                val nextTargetTime = if (nextNoteIndex < notes.size) notes[nextNoteIndex].timeMs else song.durationMs
                val diffToNext = ((nextTargetTime - currentMs) / speed).toLong()
                val sleepMs = diffToNext.coerceIn(2L, 25L)
                delay(sleepMs)
            }

            if (isActive && state == PlayState.PLAYING) {
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
