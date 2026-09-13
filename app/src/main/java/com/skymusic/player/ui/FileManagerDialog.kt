package com.skymusic.player.ui

import android.app.Dialog
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Environment
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.skymusic.player.R
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object FileManagerDialog {

    fun show(
        context: Context,
        onFileSelected: (File) -> Unit,
        onOpenSystemPicker: (() -> Unit)? = null
    ) {
        val dialog = Dialog(context)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))

        val view = LayoutInflater.from(context).inflate(R.layout.layout_floating_file_manager, null)
        dialog.setContentView(view)

        val dm = context.resources.displayMetrics
        val w = (360f * dm.density).toInt().coerceAtMost((dm.widthPixels * 0.94f).toInt())
        val h = (440f * dm.density).toInt().coerceAtMost((dm.heightPixels * 0.88f).toInt())
        dialog.window?.setLayout(w, h)

        var currentBrowseDir = getInitialDownloadDir()

        val tvPath = view.findViewById<TextView>(R.id.tvFileManagerCurrentPath)
        val rvList = view.findViewById<RecyclerView>(R.id.rvFileManagerList)
        val tvEmpty = view.findViewById<TextView>(R.id.tvFileManagerEmpty)

        fun refresh() {
            tvPath.text = currentBrowseDir.absolutePath
            val files = currentBrowseDir.listFiles()?.filter { file ->
                if (file.isDirectory) {
                    !file.name.startsWith(".")
                } else {
                    val name = file.name.lowercase()
                    name.endsWith(".mid") || name.endsWith(".midi") || name.endsWith(".json") || name.endsWith(".txt")
                }
            }?.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase() })) ?: emptyList()

            if (files.isEmpty()) {
                tvEmpty.visibility = View.VISIBLE
                rvList.visibility = View.GONE
            } else {
                tvEmpty.visibility = View.GONE
                rvList.visibility = View.VISIBLE
            }

            rvList.layoutManager = LinearLayoutManager(context)
            rvList.adapter = FileAdapter(files) { file ->
                if (file.isDirectory) {
                    currentBrowseDir = file
                    refresh()
                } else {
                    dialog.dismiss()
                    onFileSelected(file)
                }
            }
        }

        view.findViewById<View>(R.id.btnFileManagerClose)?.setOnClickListener {
            dialog.dismiss()
        }

        view.findViewById<View>(R.id.btnFileManagerJumpDownload)?.setOnClickListener {
            currentBrowseDir = getInitialDownloadDir()
            refresh()
        }

        view.findViewById<View>(R.id.btnFileManagerJumpRoot)?.setOnClickListener {
            currentBrowseDir = Environment.getExternalStorageDirectory()
            refresh()
        }

        view.findViewById<View>(R.id.btnFileManagerParent)?.setOnClickListener {
            val parent = currentBrowseDir.parentFile
            if (parent != null && parent.canRead()) {
                currentBrowseDir = parent
                refresh()
            } else {
                Toast.makeText(context, "已是根目录", Toast.LENGTH_SHORT).show()
            }
        }

        refresh()
        dialog.show()
    }

    private fun getInitialDownloadDir(): File {
        val downloadDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        if (downloadDir != null && downloadDir.exists() && downloadDir.canRead()) {
            return downloadDir
        }
        val sdcard = Environment.getExternalStorageDirectory()
        val altDownload = File(sdcard, "Download")
        if (altDownload.exists() && altDownload.canRead()) {
            return altDownload
        }
        return sdcard
    }

    private class FileAdapter(
        private val files: List<File>,
        private val onItemClick: (File) -> Unit
    ) : RecyclerView.Adapter<FileAdapter.ViewHolder>() {

        class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
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
                val dateStr = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(file.lastModified()))
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
}
