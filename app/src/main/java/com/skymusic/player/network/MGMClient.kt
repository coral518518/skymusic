package com.skymusic.player.network

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.InputStream
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.io.PushbackInputStream
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
        private const val KEY_TOKEN = "saved_token"
        private const val KEY_USERNAME = "saved_username"
        private const val KEY_PASSWORD = "saved_password"

        // 默认内置抓包账密 (可随时在悬浮窗界面自定义修改)
        const val DEFAULT_USERNAME = "lolloll"
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
    private var savedToken: String? = null
    private val gson = Gson()

    init {
        loadCookies()
        savedToken = prefs.getString(KEY_TOKEN, null)
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

    fun saveToken(token: String?) {
        savedToken = token
        if (token.isNullOrBlank()) {
            prefs.edit().remove(KEY_TOKEN).apply()
        } else {
            prefs.edit().putString(KEY_TOKEN, token).apply()
        }
    }

    fun getSavedToken(): String? = savedToken

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
        savedToken = null
        prefs.edit().remove(KEY_COOKIES).remove(KEY_TOKEN).apply()
    }

    fun isLoggedIn(): Boolean {
        return cookies.isNotEmpty() || !savedToken.isNullOrBlank()
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

        // 若存在登录 Token，附带 Authorization 及 x-token 兼容支持
        val token = savedToken
        if (!token.isNullOrBlank()) {
            conn.setRequestProperty("Authorization", "Bearer $token")
            conn.setRequestProperty("x-token", token)
        }
    }

    private fun extractCookies(conn: HttpURLConnection) {
        val headerFields = conn.headerFields ?: return
        for ((key, values) in headerFields) {
            if (key != null && key.equals("Set-Cookie", ignoreCase = true)) {
                for (header in values) {
                    val parts = header.split(";")
                    if (parts.isNotEmpty()) {
                        val pair = parts[0].trim().split("=", limit = 2)
                        if (pair.size == 2) {
                            cookies[pair[0].trim()] = pair[1].trim()
                        }
                    }
                }
            }
        }
        persistCookies()
    }

    /**
     * 高稳健性 ResponseBody 读取器
     * 使用 0x1f 0x8b 头部魔数检测 GZIP，杜绝解压缩误判或乱码
     */
    private fun readResponseBody(conn: HttpURLConnection): String {
        val rawStream: InputStream = if (conn.responseCode in 200..299) {
            conn.inputStream
        } else {
            conn.errorStream ?: conn.inputStream
        }

        val rawBytes = rawStream.use { it.readBytes() }
        val isGzip = rawBytes.size >= 2 && rawBytes[0] == 0x1f.toByte() && rawBytes[1] == 0x8b.toByte()
        return if (isGzip) {
            GZIPInputStream(java.io.ByteArrayInputStream(rawBytes)).bufferedReader(Charsets.UTF_8).use { it.readText() }
        } else {
            String(rawBytes, Charsets.UTF_8)
        }
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
            Log.d(TAG, "Login response ($code): $responseBody")

            if (code in 200..299) {
                saveCredentials(targetUser, targetPass)
                // 尝试从返回体中解析可能存在的 Token
                try {
                    val root = JsonParser.parseString(responseBody)
                    if (root.isJsonObject) {
                        val obj = root.asJsonObject
                        var extractedToken: String? = null
                        if (obj.has("token") && !obj.get("token").isJsonNull) {
                            extractedToken = obj.get("token").asString
                        } else if (obj.has("data")) {
                            val dataElem = obj.get("data")
                            if (dataElem.isJsonObject) {
                                val d = dataElem.asJsonObject
                                if (d.has("token") && !d.get("token").isJsonNull) {
                                    extractedToken = d.get("token").asString
                                } else if (d.has("accessToken") && !d.get("accessToken").isJsonNull) {
                                    extractedToken = d.get("accessToken").asString
                                }
                            } else if (dataElem.isJsonPrimitive && dataElem.asJsonPrimitive.isString) {
                                extractedToken = dataElem.asString
                            }
                        }
                        if (!extractedToken.isNullOrBlank()) {
                            saveToken(extractedToken)
                            Log.i(TAG, "Extracted and saved auth token")
                        }
                    }
                } catch (_: Exception) {}

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
                Result.failure(Exception("搜索接口异常 (HTTP $code): $responseBody"))
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
            Log.d(TAG, "Download file response code: $code, length: ${responseBody.length}, snippet: ${responseBody.take(200)}")

            if (code in 200..299) {
                // 检查是否为带有业务错误码的 JSON，例如 { "success": false, "message": "..." }
                try {
                    val root = JsonParser.parseString(responseBody)
                    if (root.isJsonObject) {
                        val rootObj = root.asJsonObject
                        if (rootObj.has("success") && !rootObj.get("success").asBoolean) {
                            val msg = if (rootObj.has("message")) rootObj.get("message").asString else "接口返回失败"
                            return@withContext Result.failure(Exception(msg))
                        }

                        // 检查是否包含云存储重定向下载 URL (如 cos 或 cdn 链接)
                        var directUrl: String? = null
                        for (k in arrayOf("url", "download_url", "file_url", "fileUrl", "downloadUrl")) {
                            if (rootObj.has(k) && !rootObj.get(k).isJsonNull) {
                                val u = rootObj.get(k).asString.trim()
                                if (u.startsWith("http://") || u.startsWith("https://")) {
                                    directUrl = u
                                    break
                                }
                            }
                        }
                        if (directUrl == null && rootObj.has("data")) {
                            val d = rootObj.get("data")
                            if (d.isJsonPrimitive && d.asJsonPrimitive.isString) {
                                val u = d.asString.trim()
                                if (u.startsWith("http://") || u.startsWith("https://")) {
                                    directUrl = u
                                }
                            } else if (d.isJsonObject) {
                                val dObj = d.asJsonObject
                                for (k in arrayOf("url", "download_url", "file_url", "fileUrl", "downloadUrl", "file")) {
                                    if (dObj.has(k) && !dObj.get(k).isJsonNull) {
                                        val u = dObj.get(k).asString.trim()
                                        if (u.startsWith("http://") || u.startsWith("https://")) {
                                            directUrl = u
                                            break
                                        }
                                    }
                                }
                            }
                        }

                        if (!directUrl.isNullOrBlank()) {
                            Log.i(TAG, "Score data points to external URL: $directUrl, downloading...")
                            val extRes = fetchUrlContent(directUrl)
                            if (extRes.isSuccess) {
                                recordDownloadQuietly(scoreId)
                                return@withContext extRes
                            }
                        }
                    }
                } catch (_: Exception) {}

                // 异步发送一次下载计数审计 (与浏览器行为一致)
                recordDownloadQuietly(scoreId)
                Result.success(responseBody)
            } else {
                Result.failure(Exception("下载乐谱失败 (HTTP $code): $responseBody"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Download score file error", e)
            Result.failure(e)
        } finally {
            conn?.disconnect()
        }
    }

    private fun fetchUrlContent(targetUrl: String): Result<String> {
        var conn: HttpURLConnection? = null
        return try {
            val url = URL(targetUrl)
            conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            applyHeaders(conn, referer = BASE_URL)
            val code = conn.responseCode
            val body = readResponseBody(conn)
            if (code in 200..299) {
                Result.success(body)
            } else {
                Result.failure(Exception("拉取外链乐谱失败 (HTTP $code)"))
            }
        } catch (e: Exception) {
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
