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
import android.text.Editable
import android.text.TextWatcher
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import android.graphics.Color
import android.content.ClipData
import android.content.ClipboardManager
import android.graphics.Bitmap
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import com.skymusic.player.web.SkyMusicWebBridge
import com.skymusic.player.MainActivity
import com.skymusic.player.R
import com.skymusic.player.SkyMusicApp
import com.skymusic.player.engine.KeyLayoutManager
import com.skymusic.player.engine.PlayEngine
import com.skymusic.player.engine.PlayState
import com.skymusic.player.engine.RootTouchController
import com.skymusic.player.model.Song
import com.skymusic.player.parser.JianpuGenerator
import com.skymusic.player.parser.OnlineScoreParser
import com.skymusic.player.parser.SheetImporter
import com.skymusic.player.ui.KeyVisualizerView
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

    // 乐谱曲库（内置与已下载）可搜索选择浮层
    private var songPickerView: View? = null
    private var songPickerParams: WindowManager.LayoutParams? = null
    private var isSongPickerAdded = false

    // 音游伴侣内嵌网页浮层视图与参数
    private var onlineView: View? = null
    private var onlineParams: WindowManager.LayoutParams? = null
    private var isOnlineAdded = false
    private var onlineWebView: WebView? = null

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

    // ----------------------------------------------------------------
    // 2.4 悬浮窗内置乐谱曲库（内置与已下载）可搜索选择浮层
    // ----------------------------------------------------------------
    private fun showSongPickerMenu() {
        showSongPickerOverlay()
    }

    private fun initSongPickerOverlay() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val dm = resources.displayMetrics
        val width = (340f * dm.density).toInt().coerceAtMost((dm.widthPixels * 0.92f).toInt())
        val height = (410f * dm.density).toInt().coerceAtMost((dm.heightPixels * 0.88f).toInt())

        songPickerParams = WindowManager.LayoutParams(
            width,
            height,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        songPickerView = themedInflater.inflate(R.layout.layout_floating_song_picker, null)

        songPickerView?.findViewById<View>(R.id.btnSongPickerClose)?.setOnClickListener {
            hideSongPickerOverlay()
            showControlPanel()
        }

        songPickerView?.findViewById<View>(R.id.btnSongPickerBrowseFiles)?.setOnClickListener {
            hideSongPickerOverlay()
            showFileManagerOverlay()
        }

        val rv = songPickerView?.findViewById<RecyclerView>(R.id.rvSongPickerList)
        val etSearch = songPickerView?.findViewById<EditText>(R.id.etSongPickerSearch)
        val btnClear = songPickerView?.findViewById<View>(R.id.btnSongPickerClear)
        val tvEmpty = songPickerView?.findViewById<View>(R.id.tvSongPickerEmpty)
        val tvCount = songPickerView?.findViewById<TextView>(R.id.tvSongPickerCount)

        rv?.layoutManager = LinearLayoutManager(themedContext)
        val adapter = FloatingSongPickerAdapter(currentSongList) { song ->
            playEngine.loadSong(song)
            updatePanelSongInfo(song)
            playEngine.play()
            hideSongPickerOverlay()
            showControlPanel()
            Toast.makeText(this@FloatingOverlayService, "正在弹奏: 《${song.title}》", Toast.LENGTH_SHORT).show()
        }
        songPickerAdapter = adapter
        rv?.adapter = adapter

        fun filterSongs(query: String) {
            val q = query.trim()
            val filtered = if (q.isEmpty()) {
                currentSongList
            } else {
                currentSongList.filter {
                    it.title.contains(q, ignoreCase = true) ||
                    it.artist.contains(q, ignoreCase = true) ||
                    it.id.contains(q, ignoreCase = true)
                }
            }
            adapter.updateList(filtered)
            tvCount?.text = "${filtered.size}首"
            tvEmpty?.visibility = if (filtered.isEmpty()) View.VISIBLE else View.GONE
            rv?.visibility = if (filtered.isEmpty()) View.GONE else View.VISIBLE
        }

        etSearch?.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                val q = s?.toString() ?: ""
                btnClear?.visibility = if (q.isNotEmpty()) View.VISIBLE else View.GONE
                filterSongs(q)
            }
            override fun afterTextChanged(s: Editable?) {}
        })

        btnClear?.setOnClickListener {
            etSearch?.setText("")
        }
    }

    private fun showSongPickerOverlay() {
        if (currentSongList.isEmpty()) {
            currentSongList.addAll(PresetSongs.getPresetList(this))
        }
        if (songPickerView == null) {
            initSongPickerOverlay()
        }
        if (!isSongPickerAdded && songPickerView != null && songPickerParams != null) {
            try {
                songPickerView?.findViewById<EditText>(R.id.etSongPickerSearch)?.setText("")
                songPickerAdapter?.updateList(currentSongList)
                songPickerView?.findViewById<TextView>(R.id.tvSongPickerCount)?.text = "${currentSongList.size}首"
                songPickerView?.findViewById<View>(R.id.tvSongPickerEmpty)?.visibility = View.GONE
                songPickerView?.findViewById<View>(R.id.rvSongPickerList)?.visibility = View.VISIBLE

                hideControlPanel()
                windowManager.addView(songPickerView, songPickerParams)
                isSongPickerAdded = true
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to show song picker overlay", e)
            }
        }
    }

    private fun hideSongPickerOverlay() {
        if (isSongPickerAdded && songPickerView != null) {
            try {
                windowManager.removeView(songPickerView)
                isSongPickerAdded = false
            } catch (e: Throwable) {
                Log.e(TAG, "Failed to hide song picker overlay", e)
            }
        }
    }

    // ----------------------------------------------------------------
    // 2.5 悬浮窗内置本地文件管理器浮层 (支持在游戏悬浮窗内直接选MIDI并秒切播放)
    // ----------------------------------------------------------------
    private fun getInitialDownloadDir(): File {
        val pub = android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS)
        if (pub != null && pub.exists()) {
            val filesssDir = File(pub, "filesss")
            if (filesssDir.exists() && filesssDir.canRead()) {
                return filesssDir
            }
            if (pub.canRead()) return pub
        }
        val sdcard = android.os.Environment.getExternalStorageDirectory()
        if (sdcard != null) {
            val altFilesss = File(File(sdcard, "Download"), "filesss")
            if (altFilesss.exists() && altFilesss.canRead()) {
                return altFilesss
            }
            val altDownload = File(sdcard, "Download")
            if (altDownload.exists() && altDownload.canRead()) {
                return altDownload
            }
        }
        return sdcard ?: filesDir
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
    // 2.6 音游伴侣内嵌网页浮层 (集成油猴脚本截获、双向已下载标记、直接弹奏与本地保存)
    // ----------------------------------------------------------------
    private fun initOnlineOverlay() {
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val dm = resources.displayMetrics
        val isLandscape = dm.widthPixels > dm.heightPixels
        val width = if (isLandscape) {
            (dm.widthPixels * 0.72f).toInt().coerceAtMost((720f * dm.density).toInt())
        } else {
            (dm.widthPixels * 0.94f).toInt()
        }
        val height = if (isLandscape) {
            (dm.heightPixels * 0.88f).toInt().coerceAtMost((500f * dm.density).toInt())
        } else {
            (dm.heightPixels * 0.82f).toInt().coerceAtMost((560f * dm.density).toInt())
        }

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
        val header = v.findViewById<View>(R.id.llOnlineHeader)
        val tvTitle = v.findViewById<TextView>(R.id.tvOnlineTitle)
        val btnBack = v.findViewById<ImageButton>(R.id.btnWebBack)
        val btnForward = v.findViewById<ImageButton>(R.id.btnWebForward)
        val btnRefresh = v.findViewById<ImageButton>(R.id.btnWebRefresh)
        val btnHome = v.findViewById<ImageButton>(R.id.btnWebHome)
        val btnClose = v.findViewById<ImageButton>(R.id.btnOnlineClose)
        val pbLoading = v.findViewById<ProgressBar>(R.id.pbWebLoading)
        val webView = v.findViewById<WebView>(R.id.wvOnlineMusic)
        onlineWebView = webView

        setupOnlineDrag(header)

        // 配置 WebView 属性与 JS 桥接
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            useWideViewPort = true
            loadWithOverviewMode = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            allowFileAccess = true
            userAgentString = "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 SkyMusic/1.0"
        }

        // 注入 Android 原生 JSBridge，彻底免除外部 PC Python 依赖
        webView.addJavascriptInterface(com.skymusic.player.web.SkyMusicWebBridge(this), "SkyMusicBridge")

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                pbLoading?.visibility = View.VISIBLE
                injectUserScript(view)
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                pbLoading?.visibility = View.GONE
                injectUserScript(view)
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                pbLoading?.progress = newProgress
                if (newProgress >= 100) {
                    pbLoading?.visibility = View.GONE
                }
            }

            override fun onReceivedTitle(view: WebView?, title: String?) {
                super.onReceivedTitle(view, title)
                if (!title.isNullOrBlank() && !title.contains("http", ignoreCase = true)) {
                    tvTitle?.text = title
                }
            }
        }

        btnBack?.setOnClickListener {
            if (webView.canGoBack()) webView.goBack()
        }

        btnForward?.setOnClickListener {
            if (webView.canGoForward()) webView.goForward()
        }

        btnRefresh?.setOnClickListener {
            webView.reload()
        }

        btnHome?.setOnClickListener {
            webView.loadUrl("https://mgm.jie-you.cn/scores")
        }

        btnClose?.setOnClickListener {
            hideOnlineOverlay()
            showControlPanel()
        }
    }

    private fun injectUserScript(view: WebView?) {
        if (view == null) return
        try {
            val script = assets.open("mgm_inject.js").bufferedReader(Charsets.UTF_8).use { it.readText() }
            view.evaluateJavascript(script, null)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to inject mgm_inject.js", e)
        }
    }

    private fun setupOnlineDrag(header: View?) {
        if (header == null) return
        var startX = 0
        var startY = 0
        var touchDownX = 0f
        var touchDownY = 0f

        header.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = onlineParams?.x ?: 0
                    startY = onlineParams?.y ?: 0
                    touchDownX = event.rawX
                    touchDownY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - touchDownX).toInt()
                    val dy = (event.rawY - touchDownY).toInt()
                    onlineParams?.x = startX + dx
                    onlineParams?.y = startY + dy
                    if (isOnlineAdded && onlineView != null && onlineParams != null) {
                        try {
                            windowManager.updateViewLayout(onlineView, onlineParams)
                        } catch (_: Throwable) {}
                    }
                    true
                }
                else -> false
            }
        }
    }

    private fun showOnlineOverlay() {
        if (onlineView == null) {
            initOnlineOverlay()
        }
        if (!isOnlineAdded && onlineView != null && onlineParams != null) {
            try {
                windowManager.addView(onlineView, onlineParams)
                isOnlineAdded = true
                if (onlineWebView?.url == null) {
                    onlineWebView?.loadUrl("https://mgm.jie-you.cn/scores")
                }
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

    // ----------------------------------------------------------------
    // JSBridge 供网页油猴脚本调用的原生接口
    // ----------------------------------------------------------------
    fun getDownloadedIdsJson(): String {
        return com.skymusic.player.parser.JianpuGenerator.getDownloadedIndexJson(this)
    }

    fun isScoreDownloaded(scoreId: Long, title: String): Boolean {
        return com.skymusic.player.parser.JianpuGenerator.isScoreDownloaded(this, scoreId, title)
    }

    fun copyToClipboard(text: String) {
        serviceScope.launch(Dispatchers.Main) {
            try {
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("SkyMusic", text)
                cm.setPrimaryClip(clip)
                Toast.makeText(this@FloatingOverlayService, "已复制弹琴 JSON 到剪贴板！", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@FloatingOverlayService, "复制失败: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun showToastFromWeb(msg: String) {
        serviceScope.launch(Dispatchers.Main) {
            Toast.makeText(this@FloatingOverlayService, msg, Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * 核心逻辑：处理从内嵌音游伴侣网页提取的曲谱
     * 1. 优先检查本地内置预设或手机 Download/filesss/ 目录：若存在则免下载直接播放
     * 2. 若本地不存在：将网页端提取的原版 JSON 与自动生成的简谱保存至 Download/filesss/，再开始演奏
     */
    fun handleScoreFromWeb(
        scoreId: Long,
        title: String,
        rawJson: String,
        autoPlay: Boolean
    ) {
        serviceScope.launch(Dispatchers.IO) {
            try {
                val cleanTitle = title.trim().ifBlank { "乐谱_$scoreId" }

                // 1. 优先检查本地是否已经存在已保存的乐谱 (内置 assets / Download/filesss/ 目录等)
                val localScore = com.skymusic.player.parser.JianpuGenerator.findLocalScore(
                    this@FloatingOverlayService,
                    scoreId,
                    cleanTitle
                )

                var finalJson = rawJson
                var isLocalHit = false

                if (localScore != null && localScore.jsonContent.isNotBlank()) {
                    Log.i(TAG, "⚡ Local cache hit for 《$cleanTitle》 (id=$scoreId)! 免下载直接播放")
                    finalJson = localScore.jsonContent
                    isLocalHit = true
                }

                // 若本地未命中且前端未传入 JSON (例如刚点进页面还未解密完)，提示稍候
                if (finalJson.isBlank()) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(this@FloatingOverlayService, "⏳ 正在提取曲谱音符数据，请稍候...", Toast.LENGTH_SHORT).show()
                    }
                    return@launch
                }

                // 2. 智能解析为 App 原生 Song 模型 (15 键 NoteEvent 时间轴)
                var song = com.skymusic.player.parser.OnlineScoreParser.parse(finalJson, cleanTitle)

                // 若本地缓存解析出 0 音符 (可能被意外截断)，回退到网页提取的 rawJson
                if (song.notes.isEmpty() && isLocalHit && rawJson.isNotBlank()) {
                    Log.w(TAG, "Local file for 《$cleanTitle》 had 0 notes, falling back to web captured JSON...")
                    finalJson = rawJson
                    isLocalHit = false
                    song = com.skymusic.player.parser.OnlineScoreParser.parse(finalJson, cleanTitle)
                }

                if (song.notes.isEmpty()) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(this@FloatingOverlayService, "❌ 乐谱未包含有效音符，无法演奏", Toast.LENGTH_LONG).show()
                    }
                    return@launch
                }

                // 3. 核心需求：若本地未保存，自动按标准算法转为简谱并保存至 Download/filesss/ 目录
                var saveMsg = "读取自本地: Download/filesss/"
                if (!isLocalHit) {
                    val saveResult = com.skymusic.player.parser.JianpuGenerator.convertAndSaveToFilesss(
                        this@FloatingOverlayService,
                        song,
                        finalJson,
                        scoreId
                    )
                    saveMsg = if (saveResult.isSuccess) {
                        "已自动存入: Download/filesss/${song.title}_简谱.txt"
                    } else {
                        "保存提示: ${saveResult.exceptionOrNull()?.message}"
                    }
                    Log.i(TAG, "Save result: $saveMsg")
                }

                // 通知网页端更新已下载状态与卡片打标
                withContext(Dispatchers.Main) {
                    val safeJsTitle = song.title.replace("'", "\\'").replace("\"", "\\\"")
                    onlineWebView?.evaluateJavascript("window.onScoreSavedFromApp?.($scoreId, '$safeJsTitle');", null)

                    if (autoPlay) {
                        // 4. 接入弹奏逻辑：载入 PlayEngine 并无缝触发钢琴演奏
                        val existingIndex = currentSongList.indexOfFirst { it.id == song.id || it.title == song.title }
                        if (existingIndex >= 0) {
                            currentSongList[existingIndex] = song
                        } else {
                            currentSongList.add(0, song)
                        }

                        playEngine.loadSong(song)
                        updatePanelSongInfo(song)
                        playEngine.play()

                        // 关闭网页浮层，唤出控制面板
                        hideOnlineOverlay()
                        showControlPanel()

                        // 检查无障碍或 Root 授权状态
                        val isRoot = RootTouchController.isRootModeEnabled(this@FloatingOverlayService)
                        val isAccessibility = SkyAccessibilityService.instance != null
                        val modeWarning = if (!isRoot && !isAccessibility) {
                            "\n⚠️ 提示：未开启「无障碍服务」或「Root模式」，屏幕钢琴无法自动点击！"
                        } else ""

                        val sourceTag = if (isLocalHit) "【⚡ 本地直读·免下载】" else "【💾 已下载并保存】"
                        Toast.makeText(
                            this@FloatingOverlayService,
                            "$sourceTag\n已开始演奏《${song.title}》 (${song.noteCount}音符)\n$saveMsg$modeWarning",
                            Toast.LENGTH_LONG
                        ).show()
                    } else {
                        Toast.makeText(
                            this@FloatingOverlayService,
                            "【💾 已存入 Download/filesss】\n《${song.title}》保存成功",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            } catch (e: Throwable) {
                Log.e(TAG, "Unexpected error in handleScoreFromWeb", e)
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@FloatingOverlayService, "乐谱处理异常: ${e.message}", Toast.LENGTH_LONG).show()
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
        if (isSongPickerAdded && songPickerView != null) {
            try { windowManager.removeView(songPickerView) } catch (_: Throwable) {}
            isSongPickerAdded = false
        }
        if (isOnlineAdded && onlineView != null) {
            try { windowManager.removeView(onlineView) } catch (_: Throwable) {}
            isOnlineAdded = false
        }
        try {
            onlineWebView?.apply {
                stopLoading()
                loadUrl("about:blank")
                destroy()
            }
        } catch (_: Throwable) {}
        onlineWebView = null
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

class FloatingSongPickerAdapter(
    private var items: List<Song>,
    private val onSelect: (Song) -> Unit
) : RecyclerView.Adapter<FloatingSongPickerAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvIndex: TextView = view.findViewById(R.id.tvSongIndex)
        val tvTitle: TextView = view.findViewById(R.id.tvSongTitle)
        val tvSubtitle: TextView = view.findViewById(R.id.tvSongSubtitle)
        val btnPlay: View = view.findViewById(R.id.btnSongPlay)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.layout_item_floating_picker_song, parent, false)
        return ViewHolder(v)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val song = items[position]
        holder.tvIndex.text = "${position + 1}"
        holder.tvTitle.text = song.title
        val typeStr = if (song.isPreset) "内置" else "下载"
        val bpmStr = if (song.bpm > 0) "${song.bpm} BPM" else ""
        val notesStr = if (song.noteCount > 0) "${song.noteCount}音符" else ""
        holder.tvSubtitle.text = listOf(typeStr, notesStr, bpmStr).filter { it.isNotBlank() }.joinToString(" · ")

        val clickListener = View.OnClickListener { onSelect(song) }
        holder.itemView.setOnClickListener(clickListener)
        holder.btnPlay.setOnClickListener(clickListener)
    }

    override fun getItemCount(): Int = items.size

    fun updateList(newItems: List<Song>) {
        items = newItems
        notifyDataSetChanged()
    }
}
