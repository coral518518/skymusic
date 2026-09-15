package com.skymusic.player.network

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.InputStream
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.zip.GZIPInputStream

/**
 * 音游伴侣 (mgm.jie-you.cn) 专用网络客户端
 * 严格使用浏览器抓包完全一致的请求头与安全指纹，防止被腾讯云 EdgeOne WAF 判定为异常爬虫
 */
class MGMClient private constructor(private val context: Context) {

    companion object {
        private const val TAG = "MGMClient"
        const val BASE_URL = "https://mgm.jie-you.cn"
        private const val PREFS_NAME = "mgm_network_prefs"
        private const val KEY_COOKIES = "saved_cookies"
        private const val KEY_USERNAME = "saved_username"
        private const val KEY_PASSWORD = "saved_password"

        // 默认内置抓包账密 (可随时在悬浮窗界面自定义修改)
        const val DEFAULT_USERNAME = "lollol"
        const val DEFAULT_PASSWORD = "123456"

        @Volatile
        private var instance: MGMClient? = null

        fun getInstance(context: Context): MGMClient {
            return instance ?: synchronized(this) {
                instance ?: MGMClient(context.applicationContext).also { instance = it }
            }
        }
    }

    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val cookies = mutableMapOf<String, String>()
    private val gson = Gson()

    init {
        loadCookies()
    }

    /**
     * 保存账密设置
     */
    fun saveCredentials(username: String, password: String) {
        prefs.edit()
            .putString(KEY_USERNAME, username)
            .putString(KEY_PASSWORD, password)
            .apply()
    }

    fun getSavedUsername(): String {
        return prefs.getString(KEY_USERNAME, DEFAULT_USERNAME) ?: DEFAULT_USERNAME
    }

    fun getSavedPassword(): String {
        return prefs.getString(KEY_PASSWORD, DEFAULT_PASSWORD) ?: DEFAULT_PASSWORD
    }

    private fun loadCookies() {
        val saved = prefs.getString(KEY_COOKIES, null) ?: return
        try {
            saved.split(";").forEach { part ->
                val pair = part.trim().split("=", limit = 2)
                if (pair.size == 2) {
                    cookies[pair[0].trim()] = pair[1].trim()
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Error loading saved cookies", e)
        }
    }

    private fun persistCookies() {
        val cookieStr = cookies.entries.joinToString("; ") { "${it.key}=${it.value}" }
        prefs.edit().putString(KEY_COOKIES, cookieStr).apply()
    }

    fun clearCookies() {
        cookies.clear()
        prefs.edit().remove(KEY_COOKIES).apply()
    }

    fun isLoggedIn(): Boolean {
        return cookies.isNotEmpty()
    }

    /**
     * 应用与网页抓包 100% 严格一致的原装请求头
     */
    private fun applyHeaders(conn: HttpURLConnection, referer: String? = null, isPost: Boolean = false) {
        conn.connectTimeout = 15000
        conn.readTimeout = 20000
        conn.useCaches = false

        // 原装 Headers (取自 req.txt 抓包报文)
        conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
        conn.setRequestProperty("Accept", "*/*")
        conn.setRequestProperty("Accept-Language", "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7")
        conn.setRequestProperty("Accept-Encoding", "gzip, deflate")
        conn.setRequestProperty("sec-ch-ua", "\"Chromium\";v=\"152\", \"Not?A_Brand\";v=\"24\", \"Google Chrome\";v=\"152\"")
        conn.setRequestProperty("sec-ch-ua-mobile", "?0")
        conn.setRequestProperty("sec-ch-ua-platform", "\"Windows\"")
        conn.setRequestProperty("sec-fetch-dest", "empty")
        conn.setRequestProperty("sec-fetch-mode", "cors")
        conn.setRequestProperty("sec-fetch-site", "same-origin")
        conn.setRequestProperty("Pragma", "no-cache")
        conn.setRequestProperty("Cache-Control", "no-cache")
        conn.setRequestProperty("priority", "u=1, i")

        if (isPost) {
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Origin", BASE_URL)
        }

        conn.setRequestProperty("Referer", referer ?: "$BASE_URL/scores")

        // 附带当前所有有效 Session Cookies
        if (cookies.isNotEmpty()) {
            val cookieHeader = cookies.entries.joinToString("; ") { "${it.key}=${it.value}" }
            conn.setRequestProperty("Cookie", cookieHeader)
        }
    }

    private fun extractCookies(conn: HttpURLConnection) {
        val headerFields = conn.headerFields
        val setCookies = headerFields["Set-Cookie"] ?: headerFields["set-cookie"] ?: return
        for (header in setCookies) {
            val parts = header.split(";")
            if (parts.isNotEmpty()) {
                val pair = parts[0].trim().split("=", limit = 2)
                if (pair.size == 2) {
                    cookies[pair[0].trim()] = pair[1].trim()
                }
            }
        }
        persistCookies()
    }

    private fun readResponseBody(conn: HttpURLConnection): String {
        val stream: InputStream = if (conn.responseCode in 200..299) {
            conn.inputStream
        } else {
            conn.errorStream ?: conn.inputStream
        }

        val encoding = conn.contentEncoding
        val effectiveStream = if (encoding != null && encoding.contains("gzip", ignoreCase = true)) {
            GZIPInputStream(stream)
        } else {
            stream
        }

        return BufferedReader(InputStreamReader(effectiveStream, "UTF-8")).use { it.readText() }
    }

    // =========================================================================
    // 接口 1: 登录 (Login)
    // =========================================================================
    suspend fun login(username: String? = null, password: String? = null): Result<Boolean> = withContext(Dispatchers.IO) {
        val targetUser = username ?: getSavedUsername()
        val targetPass = password ?: getSavedPassword()

        val url = URL("$BASE_URL/web-api/user/auth/login")
        var conn: HttpURLConnection? = null
        try {
            conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            applyHeaders(conn, referer = "$BASE_URL/login", isPost = true)

            val payload = mapOf(
                "username" to targetUser,
                "password" to targetPass,
                "device_name" to "Web 浏览器",
                "platform" to "web"
            )
            val jsonPayload = gson.toJson(payload)

            OutputStreamWriter(conn.outputStream, "UTF-8").use {
                it.write(jsonPayload)
                it.flush()
            }

            val code = conn.responseCode
            extractCookies(conn)
            val responseBody = readResponseBody(conn)

            if (code in 200..299) {
                saveCredentials(targetUser, targetPass)
                Result.success(true)
            } else {
                Result.failure(Exception("登录失败 (HTTP $code): $responseBody"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Login error", e)
            Result.failure(e)
        } finally {
            conn?.disconnect()
        }
    }

    // =========================================================================
    // 接口 2: 乐谱搜索 / 列表 (Search Scores)
    // =========================================================================
    suspend fun searchScores(
        keyword: String = "",
        page: Int = 1,
        pageSize: Int = 20,
        sort: String = "hot" // "hot" 或 "latest"
    ): Result<MGMSearchResult> = withContext(Dispatchers.IO) {
        val encodedKeyword = try {
            URLEncoder.encode(keyword.trim(), "UTF-8")
        } catch (e: Exception) {
            keyword.trim()
        }

        val urlStr = "$BASE_URL/web-api/business/scores?page=$page&pageSize=$pageSize&keyword=$encodedKeyword&sort=$sort"
        val url = URL(urlStr)
        var conn: HttpURLConnection? = null
        try {
            conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            applyHeaders(conn, referer = "$BASE_URL/scores")

            val code = conn.responseCode
            extractCookies(conn)
            val responseBody = readResponseBody(conn)

            if (code in 200..299) {
                val jsonObject = JsonParser.parseString(responseBody).asJsonObject
                if (jsonObject.has("success") && jsonObject.get("success").asBoolean) {
                    val dataObj = jsonObject.getAsJsonObject("data")
                    val itemsArray = dataObj.getAsJsonArray("items")

                    val items = mutableListOf<MGMSongItem>()
                    for (elem in itemsArray) {
                        if (!elem.isJsonObject) continue
                        val item = elem.asJsonObject

                        val id = if (item.has("id")) item.get("id").asLong else 0L
                        val title = if (item.has("title") && !item.get("title").isJsonNull) item.get("title").asString else "未命名"
                        val artist = if (item.has("artist") && !item.get("artist").isJsonNull) item.get("artist").asString else null
                        val creator = if (item.has("creator") && !item.get("creator").isJsonNull) item.get("creator").asString else null
                        val bpm = if (item.has("bpm") && !item.get("bpm").isJsonNull) item.get("bpm").asInt else 120
                        val durationMs = if (item.has("duration_ms") && !item.get("duration_ms").isJsonNull) item.get("duration_ms").asLong else 0L
                        val noteCount = if (item.has("note_count") && !item.get("note_count").isJsonNull) item.get("note_count").asInt else 0
                        val trackCount = if (item.has("track_count") && !item.get("track_count").isJsonNull) item.get("track_count").asInt else 1
                        val pricePoints = if (item.has("price_points") && !item.get("price_points").isJsonNull) item.get("price_points").asInt else 0

                        items.add(
                            MGMSongItem(
                                id = id,
                                title = title,
                                artist = artist,
                                creator = creator,
                                bpm = bpm,
                                durationMs = durationMs,
                                noteCount = noteCount,
                                trackCount = trackCount,
                                pricePoints = pricePoints
                            )
                        )
                    }

                    val total = if (dataObj.has("total")) dataObj.get("total").asInt else items.size
                    Result.success(MGMSearchResult(page = page, pageSize = pageSize, total = total, items = items))
                } else {
                    val msg = if (jsonObject.has("message")) jsonObject.get("message").asString else "接口返回失败"
                    Result.failure(Exception(msg))
                }
            } else {
                Result.failure(Exception("搜索接口异常 (HTTP $code)"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Search scores error", e)
            Result.failure(e)
        } finally {
            conn?.disconnect()
        }
    }

    // =========================================================================
    // 接口 3: 获取乐谱文件完整音符数据 (Score File JSON)
    // 关键参数: variant=full (必须携带，防止只拿到前30%预览)
    // =========================================================================
    suspend fun downloadScoreFile(scoreId: Long): Result<String> = withContext(Dispatchers.IO) {
        val url = URL("$BASE_URL/web-api/business/scores/$scoreId/file?variant=full")
        var conn: HttpURLConnection? = null
        try {
            conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            applyHeaders(conn, referer = "$BASE_URL/scores/$scoreId")

            val code = conn.responseCode
            extractCookies(conn)
            val responseBody = readResponseBody(conn)

            if (code in 200..299) {
                // 异步发送一次下载计数审计 (与浏览器行为一致)
                recordDownloadQuietly(scoreId)
                Result.success(responseBody)
            } else {
                Result.failure(Exception("下载乐谱失败 (HTTP $code)"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Download score file error", e)
            Result.failure(e)
        } finally {
            conn?.disconnect()
        }
    }

    // =========================================================================
    // 接口 4: 乐谱下载审计记录 (Download Record)
    // =========================================================================
    private fun recordDownloadQuietly(scoreId: Long) {
        try {
            val url = URL("$BASE_URL/web-api/business/scores/$scoreId/download")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            applyHeaders(conn, referer = "$BASE_URL/scores/$scoreId", isPost = true)
            conn.doOutput = false // Content-Length: 0
            conn.responseCode // 触发请求发送
            conn.disconnect()
        } catch (_: Throwable) {}
    }
}

data class MGMSongItem(
    val id: Long,
    val title: String,
    val artist: String?,
    val creator: String?,
    val bpm: Int,
    val durationMs: Long,
    val noteCount: Int,
    val trackCount: Int,
    val pricePoints: Int
) {
    fun getFormattedDuration(): String {
        val sec = durationMs / 1000
        return String.format("%02d:%02d", sec / 60, sec % 60)
    }

    fun getDisplayAuthor(): String {
        return creator ?: artist ?: "佚名"
    }
}

data class MGMSearchResult(
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val items: List<MGMSongItem>
)
