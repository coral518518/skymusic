package com.skymusic.player.web

import android.webkit.JavascriptInterface
import com.skymusic.player.service.FloatingOverlayService

/**
 * Android 原生与音游伴侣网页注入脚本的 JSBridge
 */
class SkyMusicWebBridge(
    private val service: FloatingOverlayService
) {

    @JavascriptInterface
    fun getDownloadedIdsJson(): String {
        return service.getDownloadedIdsJson()
    }

    @JavascriptInterface
    fun isScoreDownloaded(scoreId: Long, title: String?): Boolean {
        return service.isScoreDownloaded(scoreId, title ?: "")
    }

    @JavascriptInterface
    fun playScore(scoreId: Long, title: String?, rawJson: String?) {
        service.handleScoreFromWeb(
            scoreId = scoreId,
            title = title ?: "光遇乐谱",
            rawJson = rawJson ?: "",
            autoPlay = true
        )
    }

    @JavascriptInterface
    fun saveScore(scoreId: Long, title: String?, rawJson: String?) {
        service.handleScoreFromWeb(
            scoreId = scoreId,
            title = title ?: "光遇乐谱",
            rawJson = rawJson ?: "",
            autoPlay = false
        )
    }

    @JavascriptInterface
    fun copyToClipboard(text: String?) {
        service.copyToClipboard(text ?: "")
    }

    @JavascriptInterface
    fun showToast(msg: String?) {
        service.showToastFromWeb(msg ?: "")
    }
}
