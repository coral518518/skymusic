package com.skymusic.player

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.tabs.TabLayout
import com.skymusic.player.databinding.ActivityMainBinding
import com.skymusic.player.engine.KeyLayoutManager
import com.skymusic.player.model.Song
import com.skymusic.player.parser.SheetImporter
import com.skymusic.player.service.FloatingOverlayService
import com.skymusic.player.ui.SongAdapter
import com.skymusic.player.util.PermissionHelper
import com.skymusic.player.util.PresetSongs

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var songAdapter: SongAdapter

    private val presetSongs = mutableListOf<Song>()
    private val importedSongs = mutableListOf<Song>()
    private var selectedSong: Song? = null
    private var currentTabIndex = 0

    // 文件选择器：支持 MIDI (.mid, .midi)、JSON (.json)、文本 (.txt)
    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            handleImportedUri(uri)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        initData()
        initViews()
        initScreenInfo()
    }

    override fun onResume() {
        super.onResume()
        updatePermissionStatus()
        updateFloatingServiceButton()
    }

    private fun initData() {
        presetSongs.clear()
        presetSongs.addAll(PresetSongs.getPresetList())

        selectedSong = presetSongs.firstOrNull()
        FloatingOverlayService.currentSongList.clear()
        FloatingOverlayService.currentSongList.addAll(presetSongs)
    }

    private fun initViews() {
        // 权限按钮跳转
        binding.btnAccessibilityPerm.setOnClickListener {
            PermissionHelper.requestAccessibilityPermission(this)
        }
        binding.btnFloatPerm.setOnClickListener {
            PermissionHelper.requestFloatingPermission(this)
        }

        // 悬浮窗启动/停止
        binding.btnToggleFloating.setOnClickListener {
            toggleFloatingService()
        }

        // 导入乐谱按钮
        binding.btnImportSheet.setOnClickListener {
            filePickerLauncher.launch(
                arrayOf(
                    "audio/midi",
                    "audio/mid",
                    "application/json",
                    "text/plain",
                    "*/*"
                )
            )
        }

        // RecyclerView 初始化
        songAdapter = SongAdapter(
            songs = presetSongs,
            onItemClick = { song ->
                selectedSong = song
                songAdapter.setSelected(song.id)
                Toast.makeText(this, "已选择曲目: ${song.title}", Toast.LENGTH_SHORT).show()
                if (FloatingOverlayService.isRunning) {
                    FloatingOverlayService.playEngine.loadSong(song)
                }
            },
            onPlayClick = { song ->
                selectedSong = song
                songAdapter.setSelected(song.id)
                startOrUpdateFloatingWithSong(song)
            }
        )

        binding.rvSongList.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = songAdapter
        }

        selectedSong?.let { songAdapter.setSelected(it.id) }

        // TabLayout 切换
        binding.tabLayout.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab?) {
                currentTabIndex = tab?.position ?: 0
                refreshSongListDisplay()
            }
            override fun onTabUnselected(tab: TabLayout.Tab?) {}
            override fun onTabReselected(tab: TabLayout.Tab?) {}
        })
    }

    private fun refreshSongListDisplay() {
        val currentList = if (currentTabIndex == 0) presetSongs else importedSongs
        songAdapter.updateData(currentList, selectedSong?.id)

        FloatingOverlayService.currentSongList.clear()
        FloatingOverlayService.currentSongList.addAll(
            if (importedSongs.isNotEmpty()) importedSongs + presetSongs else presetSongs
        )
    }

    private fun initScreenInfo() {
        val layoutMgr = KeyLayoutManager.getInstance(this)
        val config = layoutMgr.config
        val ratio = config.screenWidth.toFloat() / config.screenHeight.toFloat()
        binding.tvScreenInfo.text = String.format(
            "当前屏幕横向比例: %dx%d (%.2f:1) · 已智能配置15键弹奏靶心",
            config.screenWidth, config.screenHeight, ratio
        )
    }

    private fun updatePermissionStatus() {
        val hasAcc = PermissionHelper.hasAccessibilityPermission(this)
        val hasFloat = PermissionHelper.hasFloatingPermission(this)

        if (hasAcc) {
            binding.btnAccessibilityPerm.text = getString(R.string.status_enabled)
            binding.btnAccessibilityPerm.setBackgroundColor(getColor(R.color.status_green))
            binding.btnAccessibilityPerm.isEnabled = false
        } else {
            binding.btnAccessibilityPerm.text = getString(R.string.btn_enable)
            binding.btnAccessibilityPerm.setBackgroundColor(getColor(R.color.sky_primary))
            binding.btnAccessibilityPerm.isEnabled = true
        }

        if (hasFloat) {
            binding.btnFloatPerm.text = getString(R.string.status_enabled)
            binding.btnFloatPerm.setBackgroundColor(getColor(R.color.status_green))
            binding.btnFloatPerm.isEnabled = false
        } else {
            binding.btnFloatPerm.text = getString(R.string.btn_enable)
            binding.btnFloatPerm.setBackgroundColor(getColor(R.color.sky_primary))
            binding.btnFloatPerm.isEnabled = true
        }
    }

    private fun updateFloatingServiceButton() {
        if (FloatingOverlayService.isRunning) {
            binding.btnToggleFloating.text = getString(R.string.stop_floating_service)
            binding.btnToggleFloating.setBackgroundColor(getColor(R.color.status_red))
        } else {
            binding.btnToggleFloating.text = getString(R.string.start_floating_service)
            binding.btnToggleFloating.background = getDrawable(R.drawable.bg_button_gold)
        }
    }

    private fun toggleFloatingService(songToLoad: Song? = null) {
        if (!PermissionHelper.hasFloatingPermission(this)) {
            Toast.makeText(this, "请先授予「游戏悬浮窗」权限", Toast.LENGTH_SHORT).show()
            PermissionHelper.requestFloatingPermission(this)
            return
        }

        if (!PermissionHelper.hasAccessibilityPermission(this)) {
            Toast.makeText(this, "请先开启「无障碍模拟点击」服务", Toast.LENGTH_SHORT).show()
            PermissionHelper.requestAccessibilityPermission(this)
            return
        }

        val serviceIntent = Intent(this, FloatingOverlayService::class.java)
        if (FloatingOverlayService.isRunning) {
            serviceIntent.action = FloatingOverlayService.ACTION_STOP
            startService(serviceIntent)
            Toast.makeText(this, "悬浮窗已关闭", Toast.LENGTH_SHORT).show()
        } else {
            serviceIntent.action = FloatingOverlayService.ACTION_START
            val song = songToLoad ?: selectedSong
            song?.let { serviceIntent.putExtra(FloatingOverlayService.EXTRA_SONG_ID, it.id) }

            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    startForegroundService(serviceIntent)
                } else {
                    startService(serviceIntent)
                }
                Toast.makeText(this, "悬浮窗已启动！可在屏幕侧边找到金色悬浮小球", Toast.LENGTH_LONG).show()
            } catch (e: Throwable) {
                try {
                    startService(serviceIntent)
                    Toast.makeText(this, "悬浮窗已启动！可在屏幕侧边找到金色悬浮小球", Toast.LENGTH_LONG).show()
                } catch (e2: Throwable) {
                    Toast.makeText(this, "启动悬浮窗失败: ${e2.message}", Toast.LENGTH_LONG).show()
                }
            }
        }

        binding.root.postDelayed({ updateFloatingServiceButton() }, 300)
    }

    private fun startOrUpdateFloatingWithSong(song: Song) {
        if (!FloatingOverlayService.isRunning) {
            toggleFloatingService(song)
        } else {
            FloatingOverlayService.playEngine.loadSong(song)
            FloatingOverlayService.playEngine.play()
            Toast.makeText(this, "正在演奏: ${song.title}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun handleImportedUri(uri: Uri) {
        var filename = "导入乐谱"
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex >= 0) {
                    filename = cursor.getString(nameIndex)
                }
            }
        }

        try {
            val song = SheetImporter.importFromUri(this, uri, filename)
            if (song != null && song.notes.isNotEmpty()) {
                importedSongs.add(0, song)
                selectedSong = song

                // 切换到“我的导入”标签
                binding.tabLayout.getTabAt(1)?.select()
                refreshSongListDisplay()

                Toast.makeText(
                    this,
                    "成功导入《${song.title}》: 共 ${song.noteCount} 个音符",
                    Toast.LENGTH_LONG
                ).show()
            } else {
                Toast.makeText(this, "乐谱解析失败或未包含有效音符，请检查文件格式", Toast.LENGTH_LONG).show()
            }
        } catch (e: Exception) {
            Toast.makeText(this, "导入出错: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }
}
