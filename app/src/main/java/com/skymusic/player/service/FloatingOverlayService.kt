package com.skymusic.player.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.*
import android.widget.*
import androidx.core.app.NotificationCompat
import com.skymusic.player.MainActivity
import com.skymusic.player.R
import com.skymusic.player.SkyMusicApp
import com.skymusic.player.engine.KeyLayoutManager
import com.skymusic.player.engine.PlayEngine
import com.skymusic.player.engine.PlayState
import com.skymusic.player.model.Song
import com.skymusic.player.ui.KeyVisualizerView
import com.skymusic.player.util.PresetSongs

class FloatingOverlayService : Service(), PlayEngine.PlaybackListener {

    companion object {
        const val ACTION_START = "action_start_floating"
        const val ACTION_STOP = "action_stop_floating"
        const val EXTRA_SONG_ID = "extra_song_id"

        var isRunning = false
            private set

        val playEngine = PlayEngine()
        var currentSongList = mutableListOf<Song>()
    }

    private lateinit var windowManager: WindowManager
    private lateinit var layoutManager: KeyLayoutManager
    private val mainHandler = Handler(Looper.getMainLooper())

    // 悬浮小球视图
    private var ballView: View? = null
    private var ballParams: WindowManager.LayoutParams? = null

    // 播放器面板视图
    private var panelView: View? = null
    private var panelParams: WindowManager.LayoutParams? = null

    // 校准全屏浮层视图
    private var calibrateView: View? = null
    private var calibrateParams: WindowManager.LayoutParams? = null

    // 悬浮窗控件引用
    private var tvSongTitle: TextView? = null
    private var sbProgress: SeekBar? = null
    private var tvCurrentTime: TextView? = null
    private var tvTotalTime: TextView? = null
    private var btnPlayPause: ImageButton? = null
    private var tvSpeedVal: TextView? = null
    private var tvPitchVal: TextView? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        layoutManager = KeyLayoutManager.getInstance(this)
        playEngine.listener = this

        startForeground(1001, createNotification())

        initFloatingBall()
        initControlPanel()
        initCalibrateOverlay()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        val songId = intent?.getStringExtra(EXTRA_SONG_ID)
        if (songId != null) {
            val found = currentSongList.find { it.id == songId }
            if (found != null) {
                playEngine.loadSong(found)
                updatePanelSongInfo(found)
            }
        } else if (playEngine.currentSong == null && currentSongList.isNotEmpty()) {
            val first = currentSongList.first()
            playEngine.loadSong(first)
            updatePanelSongInfo(first)
        }

        return START_STICKY
    }

    private fun createNotification(): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, SkyMusicApp.CHANNEL_ID)
            .setContentTitle("光遇自动弹琴助手运行中")
            .setContentText("悬浮窗已就绪，点击返回控制台")
            .setSmallIcon(R.drawable.ic_music_note)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    // ----------------------------------------------------------------
    // 1. 极简悬浮小球
    // ----------------------------------------------------------------
    private fun initFloatingBall() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        ballParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 40
            y = 300
        }

        ballView = LayoutInflater.from(this).inflate(R.layout.layout_floating_ball, null)

        var initialX = 0
        var initialY = 0
        var initialTouchX = 0f
        var initialTouchY = 0f
        var isMoved = false

        ballView?.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = ballParams!!.x
                    initialY = ballParams!!.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    isMoved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - initialTouchX).toInt()
                    val dy = (event.rawY - initialTouchY).toInt()
                    if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
                        isMoved = true
                        ballParams!!.x = initialX + dx
                        ballParams!!.y = initialY + dy
                        windowManager.updateViewLayout(ballView, ballParams)
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!isMoved) {
                        // 单击展开控制面板
                        showControlPanel()
                    }
                    true
                }
                else -> false
            }
        }

        windowManager.addView(ballView, ballParams)
    }

    // ----------------------------------------------------------------
    // 2. 展开式播放控制面板
    // ----------------------------------------------------------------
    private fun initControlPanel() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        panelParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        panelView = LayoutInflater.from(this).inflate(R.layout.layout_floating_control, null)

        tvSongTitle = panelView?.findViewById(R.id.tvFloatSongTitle)
        sbProgress = panelView?.findViewById(R.id.sbFloatProgress)
        tvCurrentTime = panelView?.findViewById(R.id.tvFloatCurrentTime)
        tvTotalTime = panelView?.findViewById(R.id.tvFloatTotalTime)
        btnPlayPause = panelView?.findViewById(R.id.btnFloatPlayPause)
        tvSpeedVal = panelView?.findViewById(R.id.tvFloatSpeedVal)
        tvPitchVal = panelView?.findViewById(R.id.tvFloatPitchVal)

        // 收起面板
        panelView?.findViewById<View>(R.id.btnFloatMinimize)?.setOnClickListener {
            hideControlPanel()
        }

        // 播放 / 暂停
        btnPlayPause?.setOnClickListener {
            togglePlayPause()
        }

        // 上一曲 / 下一曲
        panelView?.findViewById<View>(R.id.btnFloatPrev)?.setOnClickListener {
            switchSong(-1)
        }
        panelView?.findViewById<View>(R.id.btnFloatNext)?.setOnClickListener {
            switchSong(1)
        }

        // 速度调节
        panelView?.findViewById<View>(R.id.btnFloatSpeedSlow)?.setOnClickListener {
            adjustSpeed(-0.25f)
        }
        panelView?.findViewById<View>(R.id.btnFloatSpeedFast)?.setOnClickListener {
            adjustSpeed(0.25f)
        }

        // 移调调节
        panelView?.findViewById<View>(R.id.btnFloatPitchDown)?.setOnClickListener {
            adjustTranspose(-1)
        }
        panelView?.findViewById<View>(R.id.btnFloatPitchUp)?.setOnClickListener {
            adjustTranspose(1)
        }

        // 开启校准浮层
        panelView?.findViewById<View>(R.id.btnFloatCalibrate)?.setOnClickListener {
            hideControlPanel()
            showCalibrateOverlay()
        }

        // 选歌对话菜单
        panelView?.findViewById<View>(R.id.btnFloatSelectSong)?.setOnClickListener {
            showSongPickerMenu()
        }

        // 隐藏整个悬浮球
        panelView?.findViewById<View>(R.id.btnFloatHideAll)?.setOnClickListener {
            stopSelf()
        }

        // 拖动进度条
        sbProgress?.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                if (fromUser) {
                    val song = playEngine.currentSong ?: return
                    val targetMs = (song.durationMs * (progress / 1000f)).toLong()
                    playEngine.seekTo(targetMs)
                }
            }
            override fun onStartTrackingTouch(seekBar: SeekBar?) {}
            override fun onStopTrackingTouch(seekBar: SeekBar?) {}
        })

        // 默认面板先处于收起状态
        panelView?.visibility = View.GONE
        windowManager.addView(panelView, panelParams)
    }

    private fun showControlPanel() {
        panelView?.visibility = View.VISIBLE
        ballView?.visibility = View.GONE
    }

    private fun hideControlPanel() {
        panelView?.visibility = View.GONE
        ballView?.visibility = View.VISIBLE
    }

    private fun togglePlayPause() {
        when (playEngine.state) {
            PlayState.PLAYING -> playEngine.pause()
            PlayState.PAUSED -> playEngine.resume()
            PlayState.IDLE, PlayState.COMPLETED -> playEngine.play()
        }
    }

    private fun switchSong(deltaIndex: Int) {
        if (currentSongList.isEmpty()) return
        val current = playEngine.currentSong
        val currentIndex = currentSongList.indexOfFirst { it.id == current?.id }
        val nextIndex = if (currentIndex == -1) 0 else {
            (currentIndex + deltaIndex + currentSongList.size) % currentSongList.size
        }
        val nextSong = currentSongList[nextIndex]
        playEngine.loadSong(nextSong)
        updatePanelSongInfo(nextSong)
        playEngine.play()
    }

    private fun adjustSpeed(delta: Float) {
        playEngine.speed = (playEngine.speed + delta)
        tvSpeedVal?.text = String.format("%.2fx", playEngine.speed)
    }

    private fun adjustTranspose(delta: Int) {
        playEngine.transpose += delta
        tvPitchVal?.text = if (playEngine.transpose > 0) "+${playEngine.transpose}" else "${playEngine.transpose}"
    }

    private fun updatePanelSongInfo(song: Song) {
        tvSongTitle?.text = song.title
        tvTotalTime?.text = song.getFormattedDuration()
        tvCurrentTime?.text = "00:00"
        sbProgress?.progress = 0
    }

    private fun showSongPickerMenu() {
        if (currentSongList.isEmpty()) {
            Toast.makeText(this, "曲库暂无乐谱，请先在应用内导入", Toast.LENGTH_SHORT).show()
            return
        }
        val popup = PopupMenu(ContextThemeWrapper(this, R.style.Theme_SkyMusicPlayer), panelView?.findViewById(R.id.btnFloatSelectSong)!!)
        currentSongList.forEachIndexed { index, song ->
            popup.menu.add(0, index, index, "${index + 1}. ${song.title}")
        }
        popup.setOnMenuItemClickListener { item ->
            val song = currentSongList.getOrNull(item.itemId)
            if (song != null) {
                playEngine.loadSong(song)
                updatePanelSongInfo(song)
            }
            true
        }
        popup.show()
    }

    // ----------------------------------------------------------------
    // 3. 屏幕按键对齐校准全屏浮层
    // ----------------------------------------------------------------
    private fun initCalibrateOverlay() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        calibrateParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )

        calibrateView = LayoutInflater.from(this).inflate(R.layout.layout_floating_calibrate, null)
        val visualizer = calibrateView?.findViewById<KeyVisualizerView>(R.id.keyVisualizerView)

        // 上下左右微调
        calibrateView?.findViewById<View>(R.id.btnCalibrateMoveLeft)?.setOnClickListener {
            layoutManager.moveOffset(-0.005f, 0f)
            visualizer?.refreshLayout()
        }
        calibrateView?.findViewById<View>(R.id.btnCalibrateMoveRight)?.setOnClickListener {
            layoutManager.moveOffset(0.005f, 0f)
            visualizer?.refreshLayout()
        }
        calibrateView?.findViewById<View>(R.id.btnCalibrateMoveUp)?.setOnClickListener {
            layoutManager.moveOffset(0f, -0.005f)
            visualizer?.refreshLayout()
        }
        calibrateView?.findViewById<View>(R.id.btnCalibrateMoveDown)?.setOnClickListener {
            layoutManager.moveOffset(0f, 0.005f)
            visualizer?.refreshLayout()
        }

        // 缩放微调
        calibrateView?.findViewById<View>(R.id.btnCalibrateZoomIn)?.setOnClickListener {
            layoutManager.adjustScale(0.03f)
            visualizer?.refreshLayout()
        }
        calibrateView?.findViewById<View>(R.id.btnCalibrateZoomOut)?.setOnClickListener {
            layoutManager.adjustScale(-0.03f)
            visualizer?.refreshLayout()
        }

        // 一键自动对齐
        calibrateView?.findViewById<View>(R.id.btnCalibrateAutoFit)?.setOnClickListener {
            layoutManager.autoFitCurrentScreen()
            visualizer?.refreshLayout()
            Toast.makeText(this, "已自适应当前横屏分辨率", Toast.LENGTH_SHORT).show()
        }

        // 重置
        calibrateView?.findViewById<View>(R.id.btnCalibrateReset)?.setOnClickListener {
            layoutManager.resetToDefault()
            visualizer?.refreshLayout()
        }

        // 保存并完成
        calibrateView?.findViewById<View>(R.id.btnCalibrateDone)?.setOnClickListener {
            layoutManager.saveConfig()
            hideCalibrateOverlay()
            showControlPanel()
            Toast.makeText(this, "按键校准位置已保存", Toast.LENGTH_SHORT).show()
        }

        calibrateView?.visibility = View.GONE
        windowManager.addView(calibrateView, calibrateParams)
    }

    private fun showCalibrateOverlay() {
        calibrateView?.visibility = View.VISIBLE
        calibrateView?.findViewById<KeyVisualizerView>(R.id.keyVisualizerView)?.refreshLayout()
    }

    private fun hideCalibrateOverlay() {
        calibrateView?.visibility = View.GONE
    }

    // ----------------------------------------------------------------
    // 4. PlayEngine.PlaybackListener 演奏事件响应
    // ----------------------------------------------------------------
    override fun onNoteTriggered(keys: List<Int>) {
        // 调度系统无障碍服务进行真实点击模拟
        SkyAccessibilityService.instance?.clickKeys(keys, layoutManager)

        // 在主线程刷新高亮视觉反馈
        mainHandler.post {
            val visualizer = calibrateView?.findViewById<KeyVisualizerView>(R.id.keyVisualizerView)
            if (calibrateView?.visibility == View.VISIBLE) {
                visualizer?.setActiveKeys(keys)
                mainHandler.postDelayed({ visualizer?.clearActiveKeys() }, 60)
            }
        }
    }

    override fun onProgressUpdate(currentMs: Long, totalMs: Long, progressPercent: Float) {
        mainHandler.post {
            val currentSec = currentMs / 1000
            tvCurrentTime?.text = String.format("%02d:%02d", currentSec / 60, currentSec % 60)
            sbProgress?.progress = (progressPercent * 1000).toInt()
        }
    }

    override fun onStateChanged(state: PlayState) {
        mainHandler.post {
            when (state) {
                PlayState.PLAYING -> {
                    btnPlayPause?.setImageResource(R.drawable.ic_pause)
                }
                PlayState.PAUSED, PlayState.IDLE, PlayState.COMPLETED -> {
                    btnPlayPause?.setImageResource(R.drawable.ic_play_arrow)
                }
            }
        }
    }

    override fun onSongCompleted() {
        mainHandler.post {
            btnPlayPause?.setImageResource(R.drawable.ic_play_arrow)
            sbProgress?.progress = 0
            tvCurrentTime?.text = "00:00"
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        isRunning = false
        playEngine.stop()
        playEngine.listener = null

        ballView?.let { windowManager.removeView(it) }
        panelView?.let { windowManager.removeView(it) }
        calibrateView?.let { windowManager.removeView(it) }
    }
}
