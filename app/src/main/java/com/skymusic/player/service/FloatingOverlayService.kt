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
import android.graphics.Color
import com.skymusic.player.MainActivity
import com.skymusic.player.R
import com.skymusic.player.SkyMusicApp
import com.skymusic.player.engine.KeyLayoutManager
import com.skymusic.player.engine.PlayEngine
import com.skymusic.player.engine.PlayState
import com.skymusic.player.engine.RootTouchController
import com.skymusic.player.model.Song
import com.skymusic.player.network.MGMClient
import com.skymusic.player.network.MGMSongItem
import com.skymusic.player.parser.JianpuGenerator
import com.skymusic.player.parser.OnlineScoreParser
import com.skymusic.player.parser.SheetImporter
import com.skymusic.player.ui.KeyVisualizerView
import com.skymusic.player.ui.OnlineSongAdapter
import com.skymusic.player.util.PresetSongs
import kotlinx.coroutines.*
import java.io.File

class FloatingOverlayService : Service(), PlayEngine.PlaybackListener {

    companion object {
        private const val TAG = "FloatingOverlayService"
        const val ACTION_START = "action_start_floating"
        const val ACTION_STOP = "action_stop_floating"
        const val EXTRA_SONG_ID = "extra_song_id"
        const val EXTRA_AUTO_PLAY = "extra_auto_play"

        var isRunning = false
            private set

        var instance: FloatingOverlayService? = null
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

    // 本地文件选择浮层视图与参数 (支持在悬浮窗内直接选MIDI/乐谱即选即播)
    private var filePickerView: View? = null
    private var filePickerParams: WindowManager.LayoutParams? = null
    private var isPickerAdded = false
    private var currentBrowseDir: File = getInitialDownloadDir()

    // 音游伴侣在线曲库浮层视图与参数
    private var onlineView: View? = null
    private var onlineParams: WindowManager.LayoutParams? = null
    private var isOnlineAdded = false
    private lateinit var mgmClient: com.skymusic.player.network.MGMClient
    private var onlineSongAdapter: com.skymusic.player.ui.OnlineSongAdapter? = null
    private var currentOnlineSort = "hot"

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
    private var isTrackingTouch = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        instance = this
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        layoutManager = KeyLayoutManager.getInstance(this)
        mgmClient = com.skymusic.player.network.MGMClient.getInstance(this)
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
            currentSongList.addAll(PresetSongs.getPresetList(this))
        }

        val songId = intent?.getStringExtra(EXTRA_SONG_ID)
        val autoPlay = intent?.getBooleanExtra(EXTRA_AUTO_PLAY, false) ?: false
        if (songId != null) {
            val found = currentSongList.find { it.id == songId }
            if (found != null) {
                playEngine.loadSong(found)
                updatePanelSongInfo(found)
                if (autoPlay) {
                    playEngine.play()
                }
            }
        } else if (playEngine.currentSong == null && currentSongList.isNotEmpty()) {
            val first = currentSongList.first()
            playEngine.loadSong(first)
            updatePanelSongInfo(first)
            if (autoPlay) {
                playEngine.play()
            }
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

        val panelWidthPx = (200 * density).toInt()
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

        // 选歌对话菜单 (曲库预设与已导入)
        panelView?.findViewById<View>(R.id.btnFloatSelectSong)?.setOnClickListener {
            showSongPickerMenu()
        }

        // 打开音游伴侣在线曲库浮层
        panelView?.findViewById<View>(R.id.btnFloatOnline)?.setOnClickListener {
            hideControlPanel()
            showOnlineOverlay()
        }

        // 直接打开本地文件选择浮层 (默认 Download 目录即选即播)
        panelView?.findViewById<View>(R.id.btnFloatImportMidi)?.setOnClickListener {
            hideControlPanel()
            showFileManagerOverlay()
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
                    val currentSec = targetMs / 1000
                    tvCurrentTime?.text = String.format("%02d:%02d", currentSec / 60, currentSec % 60)
                }
            }
            override fun onStartTrackingTouch(seekBar: SeekBar?) {
                isTrackingTouch = true
            }
            override fun onStopTrackingTouch(seekBar: SeekBar?) {
                isTrackingTouch = false
                val song = playEngine.currentSong ?: return
                val progress = seekBar?.progress ?: 0
                val targetMs = (song.durationMs * (progress / 1000f)).toLong()
                playEngine.seekTo(targetMs)
            }
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

    fun updatePanelSongInfo(song: Song) {
        mainHandler.post {
            tvSongTitle?.text = song.title
            tvTotalTime?.text = song.getFormattedDuration()
            tvCurrentTime?.text = "00:00"
            sbProgress?.progress = 0
        }
    }

    private fun showSongPickerMenu() {
        val anchor = panelView?.findViewById<View>(R.id.btnFloatSelectSong) ?: return
        val popup = PopupMenu(themedContext, anchor)

        // 顶部第一项：直接浏览本地文件
        popup.menu.add(0, -1, 0, "📁 浏览本地MIDI/乐谱 (Download目录)...")

        currentSongList.forEachIndexed { index, song ->
            popup.menu.add(0, index, index + 1, "${index + 1}. ${song.title}")
        }
        popup.setOnMenuItemClickListener { item ->
            if (item.itemId == -1) {
                hideControlPanel()
                showFileManagerOverlay()
            } else {
                val song = currentSongList.getOrNull(item.itemId)
                if (song != null) {
                    playEngine.loadSong(song)
                    updatePanelSongInfo(song)
                    playEngine.play()
                }
            }
            true
        }
        popup.show()
    }

    // ----------------------------------------------------------------
    // 2.5 悬浮窗内置本地文件管理器浮层 (支持在游戏悬浮窗内直接选MIDI并秒切播放)
    // ----------------------------------------------------------------
    private fun getInitialDownloadDir(): File {
        val downloadDir = android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS)
        if (downloadDir != null && downloadDir.exists() && downloadDir.canRead()) {
            return downloadDir
        }
        val sdcard = android.os.Environment.getExternalStorageDirectory()
        val altDownload = File(sdcard, "Download")
        if (altDownload.exists() && altDownload.canRead()) {
            return altDownload
        }
        return sdcard
    }

    private fun initFileManagerOverlay() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val dm = resources.displayMetrics
        val width = (340f * dm.density).toInt().coerceAtMost((dm.widthPixels * 0.92f).toInt())
        val height = (390f * dm.density).toInt().coerceAtMost((dm.heightPixels * 0.88f).toInt())

        filePickerParams = WindowManager.LayoutParams(
            width,
            height,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        filePickerView = themedInflater.inflate(R.layout.layout_floating_file_manager, null)

        filePickerView?.findViewById<View>(R.id.btnFileManagerClose)?.setOnClickListener {
            hideFileManagerOverlay()
            showControlPanel()
        }

        filePickerView?.findViewById<View>(R.id.btnFileManagerJumpDownload)?.setOnClickListener {
            currentBrowseDir = getInitialDownloadDir()
            refreshFileList()
        }

        filePickerView?.findViewById<View>(R.id.btnFileManagerJumpRoot)?.setOnClickListener {
            currentBrowseDir = android.os.Environment.getExternalStorageDirectory()
            refreshFileList()
        }

        filePickerView?.findViewById<View>(R.id.btnFileManagerParent)?.setOnClickListener {
            val parent = currentBrowseDir.parentFile
            if (parent != null && parent.canRead()) {
                currentBrowseDir = parent
                refreshFileList()
            } else {
                Toast.makeText(this, "已到达存储根目录", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun showFileManagerOverlay() {
        if (filePickerView == null) {
            initFileManagerOverlay()
        }
        if (!isPickerAdded && filePickerView != null && filePickerParams != null) {
            try {
                windowManager.addView(filePickerView, filePickerParams)
                isPickerAdded = true
                currentBrowseDir = getInitialDownloadDir()
                refreshFileList()
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to show file manager overlay", e)
            }
        }
    }

    private fun hideFileManagerOverlay() {
        if (isPickerAdded && filePickerView != null) {
            try {
                windowManager.removeView(filePickerView)
                isPickerAdded = false
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to hide file manager overlay", e)
            }
        }
    }

    private fun refreshFileList() {
        val view = filePickerView ?: return
        val tvPath = view.findViewById<TextView>(R.id.tvFileManagerCurrentPath)
        val rvList = view.findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.rvFileManagerList)
        val tvEmpty = view.findViewById<TextView>(R.id.tvFileManagerEmpty)

        tvPath?.text = currentBrowseDir.absolutePath

        val files = currentBrowseDir.listFiles()?.filter { file ->
            if (file.isDirectory) {
                !file.name.startsWith(".")
            } else {
                val name = file.name.lowercase()
                name.endsWith(".mid") || name.endsWith(".midi") || name.endsWith(".json") || name.endsWith(".txt")
            }
        }?.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase() })) ?: emptyList()

        if (files.isEmpty()) {
            tvEmpty?.visibility = View.VISIBLE
            rvList?.visibility = View.GONE
        } else {
            tvEmpty?.visibility = View.GONE
            rvList?.visibility = View.VISIBLE
        }

        rvList?.layoutManager = androidx.recyclerview.widget.LinearLayoutManager(this)
        rvList?.adapter = FloatingFileAdapter(files, onItemClick = { file ->
            if (file.isDirectory) {
                currentBrowseDir = file
                refreshFileList()
            } else {
                onSelectMusicFile(file)
            }
        })
    }

    private fun onSelectMusicFile(file: File) {
        Toast.makeText(this, "正在高保真解析《${file.name}》...", Toast.LENGTH_SHORT).show()
        serviceScope.launch(Dispatchers.IO) {
            val song = SheetImporter.importFromFile(file)
            withContext(Dispatchers.Main) {
                if (song != null && song.notes.isNotEmpty()) {
                    val existingIndex = currentSongList.indexOfFirst { it.id == song.id || it.title == song.title }
                    if (existingIndex >= 0) {
                        currentSongList[existingIndex] = song
                    } else {
                        currentSongList.add(0, song)
                    }

                    playEngine.loadSong(song)
                    updatePanelSongInfo(song)
                    playEngine.play()

                    hideFileManagerOverlay()
                    showControlPanel()

                    Toast.makeText(
                        this@FloatingOverlayService,
                        "已开始演奏《${song.title}》 (共 ${song.noteCount} 个音符)",
                        Toast.LENGTH_LONG
                    ).show()
                } else {
                    Toast.makeText(
                        this@FloatingOverlayService,
                        "无法识别乐谱或未包含有效音符，请检查文件格式",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    // ----------------------------------------------------------------
    // 2.6 音游伴侣在线曲库浮层 (支持在线搜索、登录配置、下载、自动转简谱并秒切播放)
    // ----------------------------------------------------------------
    private fun initOnlineOverlay() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val dm = resources.displayMetrics
        val width = (350f * dm.density).toInt().coerceAtMost((dm.widthPixels * 0.94f).toInt())
        val height = (420f * dm.density).toInt().coerceAtMost((dm.heightPixels * 0.90f).toInt())

        onlineParams = WindowManager.LayoutParams(
            width,
            height,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        onlineView = themedInflater.inflate(R.layout.layout_floating_online_music, null)

        val v = onlineView ?: return
        val btnClose = v.findViewById<ImageButton>(R.id.btnOnlineClose)
        val btnAccountToggle = v.findViewById<Button>(R.id.btnOnlineAccountToggle)
        val drawer = v.findViewById<LinearLayout>(R.id.llOnlineAccountDrawer)
        val etUser = v.findViewById<EditText>(R.id.etOnlineUsername)
        val etPass = v.findViewById<EditText>(R.id.etOnlinePassword)
        val btnSaveLogin = v.findViewById<Button>(R.id.btnOnlineSaveLogin)
        val tvStatus = v.findViewById<TextView>(R.id.tvOnlineAccountStatus)

        val etKeyword = v.findViewById<EditText>(R.id.etOnlineKeyword)
        val btnSearch = v.findViewById<Button>(R.id.btnOnlineSearch)
        val btnSort = v.findViewById<Button>(R.id.btnOnlineSortToggle)
        val rvList = v.findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.rvOnlineSongList)

        // 初始化账号与密码回显
        etUser.setText(mgmClient.getSavedUsername())
        etPass.setText(mgmClient.getSavedPassword())
        tvStatus.text = if (mgmClient.isLoggedIn()) "账号状态: 已保存登录凭据" else "账号状态: 未登录 (默认内置 lolloll)"

        // 展开/折叠账号配置抽屉
        btnAccountToggle.setOnClickListener {
            drawer.visibility = if (drawer.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }

        // 保存账密并执行登录验证
        btnSaveLogin.setOnClickListener {
            val u = etUser.text.toString().trim()
            val p = etPass.text.toString().trim()
            if (u.isEmpty() || p.isEmpty()) {
                Toast.makeText(this, "请输入用户名与密码", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            tvStatus.text = "正在登录验证中..."
            btnSaveLogin.isEnabled = false
            serviceScope.launch {
                val res = mgmClient.login(u, p)
                btnSaveLogin.isEnabled = true
                if (res.isSuccess) {
                    tvStatus.text = "账号状态: 登录成功并已持久化保存"
                    Toast.makeText(this@FloatingOverlayService, "音游伴侣账号登录成功！", Toast.LENGTH_SHORT).show()
                    drawer.visibility = View.GONE
                    performOnlineSearch(etKeyword.text.toString().trim())
                } else {
                    val err = res.exceptionOrNull()?.message ?: "未知异常"
                    tvStatus.text = "登录失败: $err"
                    Toast.makeText(this@FloatingOverlayService, "登录失败: $err", Toast.LENGTH_LONG).show()
                }
            }
        }

        // 关闭浮层并恢复主控制面板
        btnClose.setOnClickListener {
            hideOnlineOverlay()
            showControlPanel()
        }

        // 排序切换 (最热 / 最新)
        btnSort.setOnClickListener {
            if (currentOnlineSort == "hot") {
                currentOnlineSort = "latest"
                btnSort.text = "🕒最新"
            } else {
                currentOnlineSort = "hot"
                btnSort.text = "🔥最热"
            }
            performOnlineSearch(etKeyword.text.toString().trim())
        }

        // 搜索触发
        btnSearch.setOnClickListener {
            performOnlineSearch(etKeyword.text.toString().trim())
        }

        etKeyword.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH) {
                performOnlineSearch(etKeyword.text.toString().trim())
                true
            } else {
                false
            }
        }

        // 列表与适配器配置
        rvList.layoutManager = androidx.recyclerview.widget.LinearLayoutManager(this)
        onlineSongAdapter = com.skymusic.player.ui.OnlineSongAdapter(emptyList()) { songItem ->
            downloadAndPlayOnlineSong(songItem)
        }
        rvList.adapter = onlineSongAdapter
    }

    private fun showOnlineOverlay() {
        if (onlineView == null) {
            initOnlineOverlay()
        }
        if (!isOnlineAdded && onlineView != null && onlineParams != null) {
            try {
                windowManager.addView(onlineView, onlineParams)
                isOnlineAdded = true
                val etKeyword = onlineView?.findViewById<EditText>(R.id.etOnlineKeyword)
                performOnlineSearch(etKeyword?.text?.toString()?.trim() ?: "")
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to show online overlay", e)
            }
        }
    }

    private fun hideOnlineOverlay() {
        if (isOnlineAdded && onlineView != null) {
            try {
                windowManager.removeView(onlineView)
                isOnlineAdded = false
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to hide online overlay", e)
            }
        }
    }

    private fun performOnlineSearch(keyword: String) {
        val view = onlineView ?: return
        val pbLoading = view.findViewById<ProgressBar>(R.id.pbOnlineLoading)
        val tvEmpty = view.findViewById<TextView>(R.id.tvOnlineEmpty)
        val rvList = view.findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.rvOnlineSongList)

        pbLoading.visibility = View.VISIBLE
        tvEmpty.visibility = View.GONE

        serviceScope.launch {
            val result = mgmClient.searchScores(keyword = keyword, page = 1, pageSize = 30, sort = currentOnlineSort)
            pbLoading.visibility = View.GONE
            if (result.isSuccess) {
                val searchData = result.getOrNull()
                val items = searchData?.items ?: emptyList()
                if (items.isEmpty()) {
                    tvEmpty.text = if (keyword.isBlank()) "暂无乐谱推荐" else "未找到与「$keyword」相关的乐谱"
                    tvEmpty.visibility = View.VISIBLE
                    rvList.visibility = View.GONE
                } else {
                    tvEmpty.visibility = View.GONE
                    rvList.visibility = View.VISIBLE
                    onlineSongAdapter?.submitList(items)
                }
            } else {
                val err = result.exceptionOrNull()?.message ?: "网络请求异常"
                tvEmpty.text = "获取失败: $err\n请检查网络或点击【🔑 账号】登录验证"
                tvEmpty.visibility = View.VISIBLE
                rvList.visibility = View.GONE
            }
        }
    }

    private fun downloadAndPlayOnlineSong(songItem: com.skymusic.player.network.MGMSongItem) {
        val view = onlineView
        val tvTip = view?.findViewById<TextView>(R.id.tvOnlineBottomTip)

        serviceScope.launch(Dispatchers.IO) {
            try {
                // 1. 优先检查本地是否已经存在已保存的乐谱 (Download/filesss/ 目录或媒体库)
                withContext(Dispatchers.Main) {
                    tvTip?.text = "🔍 正在检查本地是否有《${songItem.title}》已存文件..."
                }

                val localScore = com.skymusic.player.parser.JianpuGenerator.findLocalScore(
                    this@FloatingOverlayService,
                    songItem.id,
                    songItem.title
                )

                var rawJson = ""
                var isLocalHit = false

                if (localScore != null && localScore.jsonContent.isNotBlank()) {
                    Log.i(TAG, "Local cache hit for 《${songItem.title}》 (id=${songItem.id})! Skipping network download.")
                    withContext(Dispatchers.Main) {
                        tvTip?.text = "⚡ 发现本地已有保存文件，免下载直接解析载入..."
                        Toast.makeText(this@FloatingOverlayService, "⚡ 读取本地文件: 《${songItem.title}》", Toast.LENGTH_SHORT).show()
                    }
                    rawJson = localScore.jsonContent
                    isLocalHit = true
                } else {
                    // 本地未找到，通过网络拉取
                    withContext(Dispatchers.Main) {
                        tvTip?.text = "⏳ 正在连接音游伴侣下载《${songItem.title}》..."
                        Toast.makeText(this@FloatingOverlayService, "正在下载《${songItem.title}》全量乐谱...", Toast.LENGTH_SHORT).show()
                    }

                    // 确保 Session Cookie 处于可用状态 (若未登录则先用已配置账密静默登录)
                    if (!mgmClient.isLoggedIn()) {
                        withContext(Dispatchers.Main) {
                            tvTip?.text = "⏳ 正在进行音游伴侣账号身份校验..."
                        }
                        val loginRes = mgmClient.login()
                        Log.d(TAG, "Auto-login result: ${loginRes.isSuccess}")
                    }

                    // 调用 GET /scores/{id}/file?variant=full 下载全量 JSON
                    withContext(Dispatchers.Main) {
                        tvTip?.text = "⏳ 正在从服务器拉取《${songItem.title}》全量音符数据..."
                    }
                    val downloadRes = mgmClient.downloadScoreFile(songItem.id)
                    if (downloadRes.isFailure) {
                        val errMsg = downloadRes.exceptionOrNull()?.message ?: "网络请求失败"
                        Log.e(TAG, "Download score file failed: $errMsg", downloadRes.exceptionOrNull())
                        withContext(Dispatchers.Main) {
                            tvTip?.text = "❌ 下载失败: $errMsg"
                            Toast.makeText(this@FloatingOverlayService, "下载乐谱失败: $errMsg", Toast.LENGTH_LONG).show()
                        }
                        return@launch
                    }

                    rawJson = downloadRes.getOrNull() ?: ""
                    Log.d(TAG, "Downloaded score rawJson length: ${rawJson.length}")
                    Log.i("MGM_DEBUG", "Downloaded score for 《${songItem.title}》 (${rawJson.length} bytes):\n$rawJson")

                    // 落地调试报文
                    com.skymusic.player.parser.JianpuGenerator.saveDebugFile(this@FloatingOverlayService, "last_download_debug.json", rawJson)
                }

                // 2. 智能解析为 App 原生 Song 模型 (15 键 NoteEvent 时间轴)
                withContext(Dispatchers.Main) {
                    tvTip?.text = "⚙️ 正在解析 15 键按键时间轴..."
                }
                var song = com.skymusic.player.parser.OnlineScoreParser.parse(rawJson, songItem.title, songItem.bpm)

                // 若本地缓存解析出 0 音符 (可能被意外截断)，自动 fallback 到网络重新下载
                if (song.notes.isEmpty() && isLocalHit) {
                    Log.w(TAG, "Local file for 《${songItem.title}》 had 0 notes, falling back to network download...")
                    withContext(Dispatchers.Main) {
                        tvTip?.text = "⚠️ 本地文件异常，正在从服务器重新拉取..."
                    }
                    if (!mgmClient.isLoggedIn()) mgmClient.login()
                    val downloadRes = mgmClient.downloadScoreFile(songItem.id)
                    if (downloadRes.isSuccess) {
                        rawJson = downloadRes.getOrNull() ?: ""
                        isLocalHit = false
                        song = com.skymusic.player.parser.OnlineScoreParser.parse(rawJson, songItem.title, songItem.bpm)
                    }
                }

                if (song.notes.isEmpty()) {
                    Log.e(TAG, "Parsed song has 0 notes! Raw JSON preview: ${rawJson.take(500)}")
                    withContext(Dispatchers.Main) {
                        tvTip?.text = "❌ 乐谱未包含有效音符 (已写入 filesss 调试文件)"
                        Toast.makeText(
                            this@FloatingOverlayService,
                            "未识别到有效按键音符\n原始报文已保存至:\nDownload/filesss/last_download_debug.json",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                    return@launch
                }

                // 3. 核心需求：后台按音游伴侣 16 槽位量化算法自动转成标准简谱，并保存至 Download/filesss/ 目录
                var saveMsg = "读取自本地: Download/filesss/"
                if (!isLocalHit || localScore?.jianpuFile == null) {
                    withContext(Dispatchers.Main) {
                        tvTip?.text = "💾 正在自动生成标准简谱并保存至 Download/filesss..."
                    }
                    val saveResult = com.skymusic.player.parser.JianpuGenerator.convertAndSaveToFilesss(
                        this@FloatingOverlayService,
                        song,
                        rawJson,
                        songItem.id
                    )
                    saveMsg = if (saveResult.isSuccess) {
                        "简谱已自动生成至:\nDownload/filesss/${song.title}_简谱.txt"
                    } else {
                        "简谱保存提示: ${saveResult.exceptionOrNull()?.message}"
                    }
                    Log.i(TAG, "Save result: $saveMsg")
                }

                withContext(Dispatchers.Main) {
                    tvTip?.text = "🎹 正在载入弹奏引擎并开始演奏..."

                    // 4. 接入现有弹奏逻辑：载入 PlayEngine 并无缝触发钢琴演奏
                    val existingIndex = currentSongList.indexOfFirst { it.id == song.id || it.title == song.title }
                    if (existingIndex >= 0) {
                        currentSongList[existingIndex] = song
                    } else {
                        currentSongList.add(0, song)
                    }

                    playEngine.loadSong(song)
                    updatePanelSongInfo(song)
                    playEngine.play()

                    // 关闭在线浮层，唤出控制面板
                    hideOnlineOverlay()
                    showControlPanel()

                    // 刷新在线列表已缓存状态
                    onlineSongAdapter?.notifyDataSetChanged()

                    // 检查无障碍或 Root 授权状态，若未开启给予明确提示
                    val isRoot = RootTouchController.isRootModeEnabled(this@FloatingOverlayService)
                    val isAccessibility = SkyAccessibilityService.instance != null
                    val modeWarning = if (!isRoot && !isAccessibility) {
                        "\n⚠️ 提示：未开启「无障碍服务」或「Root模式」，屏幕钢琴无法自动点击！"
                    } else ""

                    val sourceTag = if (isLocalHit) "【⚡ 本地直读·免下载】" else "【在线下载成功】"
                    Toast.makeText(
                        this@FloatingOverlayService,
                        "$sourceTag\n已开始演奏《${song.title}》 (${song.noteCount}音符)\n$saveMsg$modeWarning",
                        Toast.LENGTH_LONG
                    ).show()
                }
            } catch (e: Throwable) {
                Log.e(TAG, "Unexpected error in downloadAndPlayOnlineSong", e)
                withContext(Dispatchers.Main) {
                    tvTip?.text = "❌ 运行异常: ${e.message}"
                    Toast.makeText(this@FloatingOverlayService, "弹奏处理异常: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
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
            if (!isTrackingTouch) {
                val currentSec = currentMs / 1000
                tvCurrentTime?.text = String.format("%02d:%02d", currentSec / 60, currentSec % 60)
                sbProgress?.progress = (progressPercent * 1000).toInt()
            }
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
        instance = null
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
        if (isPickerAdded && filePickerView != null) {
            try { windowManager.removeView(filePickerView) } catch (_: Throwable) {}
            isPickerAdded = false
        }
        if (isOnlineAdded && onlineView != null) {
            try { windowManager.removeView(onlineView) } catch (_: Throwable) {}
            isOnlineAdded = false
        }
    }
}

class FloatingFileAdapter(
    private val files: List<File>,
    private val onItemClick: (File) -> Unit
) : androidx.recyclerview.widget.RecyclerView.Adapter<FloatingFileAdapter.ViewHolder>() {

    class ViewHolder(view: View) : androidx.recyclerview.widget.RecyclerView.ViewHolder(view) {
        val ivIcon: ImageView = view.findViewById(R.id.ivFileIcon)
        val tvName: TextView = view.findViewById(R.id.tvFileName)
        val tvInfo: TextView = view.findViewById(R.id.tvFileInfo)
        val tvTag: TextView = view.findViewById(R.id.tvFileTag)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_floating_file_entry, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val file = files[position]
        holder.tvName.text = file.name

        if (file.isDirectory) {
            holder.ivIcon.setImageResource(R.drawable.ic_folder)
            holder.ivIcon.imageTintList = android.content.res.ColorStateList.valueOf(Color.parseColor("#80D8FF"))
            val subCount = file.list()?.size ?: 0
            holder.tvInfo.text = "$subCount 个项目"
            holder.tvTag.text = "目录"
            holder.tvTag.setTextColor(Color.parseColor("#9EADC7"))
        } else {
            holder.ivIcon.setImageResource(R.drawable.ic_music_note)
            val isMidi = file.name.endsWith(".mid", ignoreCase = true) || file.name.endsWith(".midi", ignoreCase = true)
            val sizeKb = file.length() / 1024.0
            val sizeStr = if (sizeKb > 1024) String.format("%.1f MB", sizeKb / 1024) else String.format("%.1f KB", sizeKb)
            val dateStr = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.getDefault()).format(java.util.Date(file.lastModified()))
            holder.tvInfo.text = "$sizeStr · $dateStr"

            if (isMidi) {
                holder.ivIcon.imageTintList = android.content.res.ColorStateList.valueOf(Color.parseColor("#FFD54F"))
                holder.tvTag.text = "MIDI"
                holder.tvTag.setTextColor(Color.parseColor("#FFD54F"))
            } else {
                holder.ivIcon.imageTintList = android.content.res.ColorStateList.valueOf(Color.parseColor("#80D8FF"))
                holder.tvTag.text = "JSON"
                holder.tvTag.setTextColor(Color.parseColor("#80D8FF"))
            }
        }

        holder.itemView.setOnClickListener {
            onItemClick(file)
        }
    }

    override fun getItemCount(): Int = files.size
}
