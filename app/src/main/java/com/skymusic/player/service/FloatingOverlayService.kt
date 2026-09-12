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
import android.util.Log
import android.view.*
import android.widget.*
import androidx.appcompat.view.ContextThemeWrapper
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.skymusic.player.MainActivity
import com.skymusic.player.R
import com.skymusic.player.SkyMusicApp
import com.skymusic.player.engine.KeyLayoutManager
import com.skymusic.player.engine.PlayEngine
import com.skymusic.player.engine.PlayState
import com.skymusic.player.engine.RootTouchController
import com.skymusic.player.model.Song
import com.skymusic.player.ui.KeyVisualizerView
import com.skymusic.player.util.PresetSongs
import kotlinx.coroutines.*

class FloatingOverlayService : Service(), PlayEngine.PlaybackListener {

    companion object {
        private const val TAG = "FloatingOverlayService"
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
    private lateinit var themedContext: Context
    private lateinit var themedInflater: LayoutInflater
    private val mainHandler = Handler(Looper.getMainLooper())

    // 悬浮小球视图与参数
    private var ballView: View? = null
    private var ballParams: WindowManager.LayoutParams? = null
    private var isBallAdded = false

    // 播放器面板视图与参数
    private var panelView: View? = null
    private var panelParams: WindowManager.LayoutParams? = null
    private var isPanelAdded = false

    // 校准全屏浮层视图与参数
    private var calibrateView: View? = null
    private var calibrateParams: WindowManager.LayoutParams? = null
    private var isCalibrateAdded = false

    // 悬浮窗控件引用
    private var tvSongTitle: TextView? = null
    private var sbProgress: SeekBar? = null
    private var tvCurrentTime: TextView? = null
    private var tvTotalTime: TextView? = null
    private var btnPlayPause: ImageButton? = null
    private var tvSpeedVal: TextView? = null
    private var tvPitchVal: TextView? = null
    private var btnDelayRange: Button? = null
    private var btnTouchMode: Button? = null

    private val serviceScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val delayOptions = intArrayOf(0, 5, 10, 20, 30)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        layoutManager = KeyLayoutManager.getInstance(this)
        playEngine.listener = this

        // 读取防检测延迟设置
        val sp = getSharedPreferences("skymusic_settings", Context.MODE_PRIVATE)
        playEngine.randomDelayRangeMs = sp.getInt("pref_random_delay_ms", 10)

        // 使用 AppCompat 主题包装器，防止在 Service 中解析 MaterialComponents 控件时抛出异常
        themedContext = ContextThemeWrapper(this, R.style.Theme_SkyMusicPlayer)
        themedInflater = LayoutInflater.from(themedContext)

        // 安全启动前台通知，避免 Android 14/15 抛出 FGS 异常中断服务初始化
        safeStartForeground()

        // 仅在屏幕添加金色悬浮小球，控制面板与校准层按需动态显示与移除
        initFloatingBall()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        if (currentSongList.isEmpty()) {
            currentSongList.addAll(PresetSongs.getPresetList())
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

    private fun safeStartForeground() {
        try {
            val notification = createNotification()
            startForeground(1001, notification)
        } catch (e: Throwable) {
            Log.e(TAG, "safeStartForeground error: ${e.message}", e)
        }
    }

    private fun createNotification(): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, SkyMusicApp.CHANNEL_ID)
            .setContentTitle("光遇自动弹琴助手已就绪")
            .setContentText("悬浮小球已显示在屏幕上，点击可打开游戏控制台")
            .setSmallIcon(R.drawable.ic_music_note)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    // ----------------------------------------------------------------
    // 1. 极简高亮金色悬浮小球 (支持拖拽与点击展开)
    // ----------------------------------------------------------------
    private fun initFloatingBall() {
        val density = resources.displayMetrics.density
        val ballSizePx = (56 * density).toInt()

        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        ballParams = WindowManager.LayoutParams(
            ballSizePx,
            ballSizePx,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = (20 * density).toInt()
            y = (220 * density).toInt()
        }

        ballView = themedInflater.inflate(R.layout.layout_floating_ball, null)

        var initialX = 0
        var initialY = 0
        var initialTouchX = 0f
        var initialTouchY = 0f
        var isMoved = false

        ballView?.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = ballParams?.x ?: 0
                    initialY = ballParams?.y ?: 0
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
                        ballParams?.x = initialX + dx
                        ballParams?.y = initialY + dy
                        if (isBallAdded && ballView != null && ballParams != null) {
                            try {
                                windowManager.updateViewLayout(ballView, ballParams)
                            } catch (_: Throwable) {}
                        }
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!isMoved) {
                        // 单击小球，展开控制面板
                        showControlPanel()
                    }
                    true
                }
                else -> false
            }
        }

        try {
            windowManager.addView(ballView, ballParams)
            isBallAdded = true
        } catch (e: Throwable) {
            Log.e(TAG, "Failed to add ballView to windowManager", e)
            Toast.makeText(
                this,
                "悬浮球显示受阻：请在系统设置中为本应用开启「显示悬浮窗」与「后台弹出界面」权限",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    // ----------------------------------------------------------------
    // 2. 展开式播放控制面板 (按需挂载，支持拖拽与完整控制)
    // ----------------------------------------------------------------
    private fun initControlPanel() {
        val density = resources.displayMetrics.density
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val panelWidthPx = (260 * density).toInt()
        panelParams = WindowManager.LayoutParams(
            panelWidthPx,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        panelView = themedInflater.inflate(R.layout.layout_floating_control, null)

        tvSongTitle = panelView?.findViewById(R.id.tvFloatSongTitle)
        sbProgress = panelView?.findViewById(R.id.sbFloatProgress)
        tvCurrentTime = panelView?.findViewById(R.id.tvFloatCurrentTime)
        tvTotalTime = panelView?.findViewById(R.id.tvFloatTotalTime)
        btnPlayPause = panelView?.findViewById(R.id.btnFloatPlayPause)
        tvSpeedVal = panelView?.findViewById(R.id.tvFloatSpeedVal)
        tvPitchVal = panelView?.findViewById(R.id.tvFloatPitchVal)

        // 绑定标题栏拖拽面板
        setupPanelDrag()

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

        // 彻底关闭悬浮窗与后台服务
        panelView?.findViewById<View>(R.id.btnFloatHideAll)?.setOnClickListener {
            stopSelf()
        }

        // 随机延迟微抖动调节
        btnDelayRange = panelView?.findViewById(R.id.btnFloatDelayRange)
        updateDelayRangeButtonText()
        btnDelayRange?.setOnClickListener {
            cycleDelayRange()
        }

        // 触控模式切换 (无障碍 vs Root)
        btnTouchMode = panelView?.findViewById(R.id.btnFloatTouchMode)
        updateTouchModeButton()
        btnTouchMode?.setOnClickListener {
            toggleTouchMode()
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

        // 若已有加载的歌曲，回显当前信息
        playEngine.currentSong?.let { updatePanelSongInfo(it) }
    }

    private fun setupPanelDrag() {
        val header = panelView?.findViewById<View>(R.id.llFloatHeader) ?: return
        var startX = 0
        var startY = 0
        var touchDownX = 0f
        var touchDownY = 0f

        header.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = panelParams?.x ?: 0
                    startY = panelParams?.y ?: 0
                    touchDownX = event.rawX
                    touchDownY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - touchDownX).toInt()
                    val dy = (event.rawY - touchDownY).toInt()
                    panelParams?.x = startX + dx
                    panelParams?.y = startY + dy
                    if (isPanelAdded && panelView != null && panelParams != null) {
                        try {
                            windowManager.updateViewLayout(panelView, panelParams)
                        } catch (_: Throwable) {}
                    }
                    true
                }
                else -> false
            }
        }
    }

    private fun showControlPanel() {
        if (panelView == null) {
            initControlPanel()
        }
        if (!isPanelAdded && panelView != null && panelParams != null) {
            try {
                windowManager.addView(panelView, panelParams)
                isPanelAdded = true
                // 打开面板时隐藏小球，避免遮挡
                if (isBallAdded && ballView != null) {
                    windowManager.removeView(ballView)
                    isBallAdded = false
                }
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to show control panel", e)
            }
        }
    }

    private fun hideControlPanel() {
        if (isPanelAdded && panelView != null) {
            try {
                windowManager.removeView(panelView)
                isPanelAdded = false
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to hide control panel", e)
            }
        }
        // 恢复金色小球
        if (!isBallAdded && ballView != null && ballParams != null) {
            try {
                windowManager.addView(ballView, ballParams)
                isBallAdded = true
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to restore ballView", e)
            }
        }
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
            Toast.makeText(this, "曲库暂无乐谱，请先在主界面导入", Toast.LENGTH_SHORT).show()
            return
        }
        val anchor = panelView?.findViewById<View>(R.id.btnFloatSelectSong) ?: return
        val popup = PopupMenu(themedContext, anchor)
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
    // 3. 屏幕按键对齐校准全屏浮层 (按需挂载，保存后即移除)
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

        calibrateView = themedInflater.inflate(R.layout.layout_floating_calibrate, null)
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
            Toast.makeText(this, "已自适应当前屏幕分辨率", Toast.LENGTH_SHORT).show()
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
    }

    private fun showCalibrateOverlay() {
        if (calibrateView == null) {
            initCalibrateOverlay()
        }
        if (!isCalibrateAdded && calibrateView != null && calibrateParams != null) {
            try {
                windowManager.addView(calibrateView, calibrateParams)
                isCalibrateAdded = true
                calibrateView?.findViewById<KeyVisualizerView>(R.id.keyVisualizerView)?.refreshLayout()
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to show calibrate overlay", e)
            }
        }
    }

    private fun hideCalibrateOverlay() {
        if (isCalibrateAdded && calibrateView != null) {
            try {
                windowManager.removeView(calibrateView)
                isCalibrateAdded = false
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to hide calibrate overlay", e)
            }
        }
    }

    private fun updateDelayRangeButtonText() {
        val delay = playEngine.randomDelayRangeMs
        btnDelayRange?.text = if (delay == 0) "抖动: 关闭" else "抖动: ±${delay}ms"
    }

    private fun cycleDelayRange() {
        val current = playEngine.randomDelayRangeMs
        val currentIndex = delayOptions.indexOf(current)
        val nextIndex = if (currentIndex == -1) 2 else (currentIndex + 1) % delayOptions.size
        val nextDelay = delayOptions[nextIndex]
        playEngine.randomDelayRangeMs = nextDelay

        val sp = getSharedPreferences("skymusic_settings", Context.MODE_PRIVATE)
        sp.edit().putInt("pref_random_delay_ms", nextDelay).apply()

        updateDelayRangeButtonText()
        val desc = if (nextDelay == 0) "已关闭随机延迟" else "按键间隔随机抖动: ±${nextDelay}ms"
        Toast.makeText(this, desc, Toast.LENGTH_SHORT).show()
    }

    private fun updateTouchModeButton() {
        val isRoot = RootTouchController.isRootModeEnabled(this)
        btnTouchMode?.text = if (isRoot) "模式: Root" else "模式: 无障碍"
        btnTouchMode?.setTextColor(
            ContextCompat.getColor(this, if (isRoot) R.color.sky_accent else R.color.sky_primary)
        )
    }

    private fun toggleTouchMode() {
        val currentlyRoot = RootTouchController.isRootModeEnabled(this)
        if (currentlyRoot) {
            RootTouchController.setRootModeEnabled(this, false)
            updateTouchModeButton()
            Toast.makeText(this, "已切回「无障碍模拟点击」模式", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(this, "正在请求 Root 权限并建立底层通道...", Toast.LENGTH_SHORT).show()
            serviceScope.launch {
                val granted = RootTouchController.requestRootPermission()
                if (granted) {
                    RootTouchController.setRootModeEnabled(this@FloatingOverlayService, true)
                    updateTouchModeButton()
                    Toast.makeText(this@FloatingOverlayService, "Root 授权成功！已启用底层防检测触控", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(
                        this@FloatingOverlayService,
                        "未获取到 Root 权限，请在 KernelSU/APatch/Magisk 中允许授权",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    // ----------------------------------------------------------------
    // 4. PlayEngine.PlaybackListener 演奏事件响应
    // ----------------------------------------------------------------
    override fun onNoteTriggered(keys: List<Int>) {
        if (RootTouchController.isRootModeEnabled(this)) {
            // Root 底层输入注入模式 (KernelSU / APatch / Magisk，完全绕过无障碍检测)
            RootTouchController.clickKeys(keys, layoutManager)
        } else {
            // 调度系统无障碍服务进行真实模拟点击
            SkyAccessibilityService.instance?.clickKeys(keys, layoutManager)
        }

        // 在主线程刷新校准层高亮反馈 (仅在校准层处于打开状态时)
        mainHandler.post {
            if (isCalibrateAdded && calibrateView != null) {
                val visualizer = calibrateView?.findViewById<KeyVisualizerView>(R.id.keyVisualizerView)
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
        serviceScope.cancel()
        playEngine.stop()
        playEngine.listener = null

        if (isBallAdded && ballView != null) {
            try { windowManager.removeView(ballView) } catch (_: Throwable) {}
            isBallAdded = false
        }
        if (isPanelAdded && panelView != null) {
            try { windowManager.removeView(panelView) } catch (_: Throwable) {}
            isPanelAdded = false
        }
        if (isCalibrateAdded && calibrateView != null) {
            try { windowManager.removeView(calibrateView) } catch (_: Throwable) {}
            isCalibrateAdded = false
        }
    }
}
