package com.skymusic.player.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import androidx.cardview.widget.CardView
import androidx.recyclerview.widget.RecyclerView
import com.skymusic.player.R
import com.skymusic.player.model.Song

class SongAdapter(
    private var songs: List<Song>,
    private val onItemClick: (Song) -> Unit,
    private val onPlayClick: (Song) -> Unit
) : RecyclerView.Adapter<SongAdapter.SongViewHolder>() {

    private var selectedSongId: String? = null

    fun updateData(newSongs: List<Song>, selectedId: String? = null) {
        this.songs = newSongs
        this.selectedSongId = selectedId
        notifyDataSetChanged()
    }

    fun setSelected(songId: String) {
        selectedSongId = songId
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): SongViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_song, parent, false)
        return SongViewHolder(view)
    }

    override fun onBindViewHolder(holder: SongViewHolder, position: Int) {
        val song = songs[position]
        holder.bind(song, song.id == selectedSongId)
    }

    override fun getItemCount(): Int = songs.size

    inner class SongViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val card: CardView = itemView.findViewById(R.id.cardSongItem)
        private val tvTitle: TextView = itemView.findViewById(R.id.tvSongTitle)
        private val tvMeta: TextView = itemView.findViewById(R.id.tvSongMeta)
        private val tvTypeTag: TextView = itemView.findViewById(R.id.tvSongTypeTag)
        private val btnPlay: ImageButton = itemView.findViewById(R.id.btnQuickPlay)

        fun bind(song: Song, isSelected: Boolean) {
            tvTitle.text = song.title
            tvMeta.text = "${song.noteCount} 音符 · ${song.getFormattedDuration()} · ${song.bpm} BPM"
            tvTypeTag.text = song.type

            if (isSelected) {
                card.setCardBackgroundColor(itemView.context.getColor(R.color.sky_card_dark_stroke))
            } else {
                card.setCardBackgroundColor(itemView.context.getColor(R.color.sky_card_dark))
            }

            itemView.setOnClickListener {
                onItemClick(song)
            }

            btnPlay.setOnClickListener {
                onPlayClick(song)
            }
        }
    }
}
