package com.skymusic.player.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.skymusic.player.R
import com.skymusic.player.network.MGMSongItem

class OnlineSongAdapter(
    private var songs: List<MGMSongItem>,
    private val onPlayClick: (MGMSongItem) -> Unit
) : RecyclerView.Adapter<OnlineSongAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvTitle: TextView = view.findViewById(R.id.tvOnlineTitle)
        val tvTag: TextView = view.findViewById(R.id.tvOnlineTag)
        val tvInfo: TextView = view.findViewById(R.id.tvOnlineInfo)
        val btnPlay: Button = view.findViewById(R.id.btnOnlinePlay)
    }

    fun submitList(newList: List<MGMSongItem>) {
        songs = newList
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_online_song, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = songs[position]
        holder.tvTitle.text = item.title

        val authorStr = item.getDisplayAuthor()
        val durationStr = item.getFormattedDuration()
        holder.tvInfo.text = "BPM ${item.bpm} · ${item.noteCount}音符 · 作者: $authorStr · $durationStr"

        holder.tvTag.text = if (item.trackCount > 1) "${item.trackCount}轨合奏" else "15键单人"

        holder.btnPlay.setOnClickListener {
            onPlayClick(item)
        }

        holder.itemView.setOnClickListener {
            onPlayClick(item)
        }
    }

    override fun getItemCount(): Int = songs.size
}
