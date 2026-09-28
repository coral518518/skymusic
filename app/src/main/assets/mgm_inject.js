/**
 * 音游伴侣 - 网页内嵌乐谱拦截与双向通信脚本 (SkyMusic App 集成版)
 * 功能：
 * 1. 自动 Hook 浏览器 WebCrypto 解密，截获官方乐谱原始 JSON
 * 2. 桥接 Android 原生 SkyMusicBridge 实现已下载状态自动标记与直接弹奏/保存
 * 3. 本地内置/已下载直接秒播，未下载曲目自动规范化存入 Download/filesss 目录
 */
(function () {
    'use strict';

    if (window.__skymusic_injected) {
        if (window.__skymusic_refresh) window.__skymusic_refresh();
        return;
    }
    window.__skymusic_injected = true;

    console.log('[SkyMusic] 🎹 音游伴侣 App 乐谱导出扩展已就绪');

    let indexData = {
        ids: [],
        records: {},
        total_downloaded: 0
    };
    let capturedScore = null;

    // 1. 同步 Android App 本地已收录/已下载记录
    function syncIndexFromApp() {
        try {
            if (window.SkyMusicBridge && typeof window.SkyMusicBridge.getDownloadedIdsJson === 'function') {
                const jsonStr = window.SkyMusicBridge.getDownloadedIdsJson();
                if (jsonStr) {
                    const parsed = JSON.parse(jsonStr);
                    if (parsed && Array.isArray(parsed.ids)) {
                        indexData.ids = parsed.ids;
                        indexData.records = parsed.records || {};
                        indexData.total_downloaded = parsed.ids.length;
                    }
                }
            }
        } catch (e) {
            console.warn('[SkyMusic] 同步 App 索引失败:', e);
        }
    }
    syncIndexFromApp();

    // 2. 检查曲谱是否在本地已存在
    function isScoreDownloaded(sid, title) {
        if (!sid) return false;
        if (indexData.ids && indexData.ids.includes(sid)) return true;
        if (indexData.records && !!indexData.records[String(sid)]) return true;
        if (window.SkyMusicBridge && typeof window.SkyMusicBridge.isScoreDownloaded === 'function') {
            try {
                return window.SkyMusicBridge.isScoreDownloaded(sid, title || "");
            } catch (e) {}
        }
        return false;
    }

    // 3. 核心解密拦截：Hook WebCrypto AES-GCM
    if (window.crypto && window.crypto.subtle) {
        const originalDecrypt = window.crypto.subtle.decrypt.bind(window.crypto.subtle);
        window.crypto.subtle.decrypt = async function (...args) {
            const decryptedBuffer = await originalDecrypt(...args);
            try {
                const text = new TextDecoder('utf-8').decode(decryptedBuffer);
                if (text.includes('"format"') && (text.includes('"mgm.score"') || text.includes('"tracks"'))) {
                    const parsed = JSON.parse(text);
                    const scoreData = parsed?.data?.score || parsed?.score || parsed;
                    if (scoreData?.tracks || scoreData?.notes) {
                        console.log('[SkyMusic] 🎯 成功截获解密乐谱数据:', scoreData);
                        capturedScore = scoreData;
                        onScoreReady();
                    }
                }
            } catch (e) {
                console.warn('[SkyMusic] 解密解析异常:', e);
            }
            return decryptedBuffer;
        };
    }

    // 4. 标准格式化：复刻 scores 文件夹内的规范 JSON 格式
    function formatToScoresFolderStandard(rawScore) {
        let score = rawScore;
        if (rawScore && rawScore.data && rawScore.data.score) {
            score = rawScore.data.score;
        } else if (rawScore && rawScore.score) {
            score = rawScore.score;
        }

        const metadata = score.metadata || {};
        let title = metadata.title || score.title || '';
        if (!title) {
            const h1 = document.querySelector('h1');
            title = h1 ? h1.innerText.trim() : '光遇乐谱';
        }
        const bpm = score.bpm || 120;
        const tracks = score.tracks || [];

        const cleanTracks = tracks.map((t, tIdx) => {
            const rawNotes = t.notes || [];
            const notes = rawNotes.map((n, nIdx) => {
                const startMs = n.startMs ?? n.time ?? n.timeMs ?? 0;
                let pitch = n.pitch;
                let keyIdx = n.keyIndex;
                let rawKey = n.rawKey;

                if (rawKey && typeof rawKey === 'string' && rawKey.includes('Key')) {
                    const m = rawKey.match(/Key(\d+)/i);
                    if (m) {
                        const k0 = parseInt(m[1], 10);
                        if (pitch == null) pitch = k0 + 1;
                        if (keyIdx == null) keyIdx = k0 + 1;
                    }
                }
                if (keyIdx == null && pitch != null) keyIdx = pitch;
                if (pitch == null && keyIdx != null) pitch = keyIdx;
                if (pitch == null) pitch = 1;
                if (keyIdx == null) keyIdx = 1;

                if (!rawKey) rawKey = `1Key${keyIdx - 1}`;
                const targetKey = n.targetKey || `sky.key.${keyIdx}`;

                return {
                    id: n.id || `t${tIdx + 1}_n${nIdx + 1}`,
                    startMs: startMs,
                    durationMs: n.durationMs ?? 0,
                    pitch: pitch,
                    keyIndex: keyIdx,
                    velocity: n.velocity ?? 100,
                    rawKey: rawKey,
                    targetKey: targetKey
                };
            });

            notes.sort((a, b) => a.startMs - b.startMs);

            return {
                id: t.id || `track_${tIdx + 1}`,
                name: t.name || `Sky 轨道 ${tIdx + 1}`,
                instrument: t.instrument || 'sky_piano',
                muted: !!t.muted,
                solo: !!t.solo,
                preview: t.preview || {
                    defaultInstrument: 'sky_piano',
                    metronome: false,
                    countInBeats: 0
                },
                notes: notes
            };
        });

        let totalNotes = 0;
        let maxMs = 0;
        cleanTracks.forEach(tr => {
            totalNotes += tr.notes.length;
            tr.notes.forEach(nt => {
                if (nt.startMs > maxMs) maxMs = nt.startMs;
            });
        });

        const cleanScore = {
            format: score.format || 'mgm.score',
            version: score.version || 1,
            durationMs: score.durationMs || maxMs,
            noteCount: score.noteCount || totalNotes,
            trackCount: cleanTracks.length,
            bpm: bpm,
            metadata: {
                title: title,
                artist: metadata.artist || score.artist || '网络',
                creator: metadata.creator || score.creator || '网络',
                description: metadata.description || '',
                sourceFormat: metadata.sourceFormat || 'sky-studio-json'
            },
            timing: score.timing || {
                timeBase: 'milliseconds',
                bpm: bpm,
                offsetMs: 0
            },
            range: score.range || {
                code: '15',
                keyCount: 15
            },
            preview: score.preview || {
                defaultInstrument: 'sky_piano',
                metronome: false,
                countInBeats: 0
            },
            target: score.target || {
                platform: 'android',
                game: 'sky',
                layoutProfileId: '',
                clickMode: 'accessibility'
            },
            tracks: cleanTracks
        };

        return {
            success: true,
            data: {
                score: cleanScore
            }
        };
    }

    // 5. 转换 Sky Studio 剪贴板弹琴数组
    function convertToSkyStudioClipboard(scoreObj) {
        const score = scoreObj.data?.score || scoreObj;
        const title = score.metadata?.title || score.title || '光遇乐谱';
        const bpm = score.bpm || 120;
        const tracks = score.tracks || [];

        const songNotes = [];
        for (const t of tracks) {
            const tname = String(t.name || '').toLowerCase();
            const tinst = String(t.instrument || '').toLowerCase();
            const isPercussion = ['drum', 'tr_909', 'sfx', 'percussion', '鼓', '打击乐'].some(p => tname.includes(p) || tinst.includes(p));
            if (isPercussion && tracks.length > 1) continue;

            for (const n of (t.notes || [])) {
                const timeMs = n.startMs ?? 0;
                let keyIdx = n.keyIndex ? n.keyIndex - 1 : (n.pitch ? n.pitch - 1 : -1);
                if (n.rawKey && n.rawKey.includes('Key')) {
                    const m = n.rawKey.match(/Key(\d+)/i);
                    if (m) keyIdx = parseInt(m[1], 10);
                }
                if (keyIdx >= 0 && keyIdx <= 14) {
                    songNotes.push({
                        time: timeMs,
                        key: `1Key${keyIdx}`
                    });
                }
            }
        }

        songNotes.sort((a, b) => a.time - b.time);

        return JSON.stringify([
            {
                name: title,
                bpm: bpm,
                bitsPerPage: 16,
                pitchLevel: 0,
                songNotes: songNotes
            }
        ], null, 2);
    }

    function getCurrentScoreId() {
        const m = location.pathname.match(/\/scores\/(\d+)/);
        if (m) return parseInt(m[1], 10);
        if (capturedScore) {
            if (capturedScore.id) return parseInt(capturedScore.id, 10);
            if (capturedScore.scoreId) return parseInt(capturedScore.scoreId, 10);
            if (capturedScore.metadata && capturedScore.metadata.id) return parseInt(capturedScore.metadata.id, 10);
        }
        return null;
    }

    function getCurrentTitle() {
        if (capturedScore) {
            const meta = capturedScore.metadata || {};
            if (meta.title) return meta.title;
            if (capturedScore.title) return capturedScore.title;
        }
        const h1 = document.querySelector('h1');
        if (h1 && h1.innerText.trim()) return h1.innerText.trim();
        return '';
    }

    // 6. 列表卡片自动标记 [✓已下载]
    function markScoreCardsOnList() {
        const links = document.querySelectorAll('a[href*="/scores/"]');
        links.forEach(a => {
            const m = a.getAttribute('href').match(/\/scores\/(\d+)/);
            if (!m) return;
            const sid = parseInt(m[1], 10);
            const downloaded = isScoreDownloaded(sid);
            const existingTag = a.querySelector('.sky-downloaded-tag');

            if (downloaded) {
                if (!existingTag) {
                    const tag = document.createElement('span');
                    tag.className = 'sky-downloaded-tag';
                    tag.innerText = '✓已下载';
                    tag.style.cssText = 'position:absolute;top:6px;right:6px;background:#10b981;color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;z-index:10;box-shadow:0 2px 6px rgba(0,0,0,0.3);pointer-events:none;';
                    if (getComputedStyle(a).position === 'static') {
                        a.style.position = 'relative';
                    }
                    a.appendChild(tag);
                }
            } else if (existingTag) {
                existingTag.remove();
            }
        });
    }

    // 7. 注入轻量悬浮面板 (适配 Android 手机与横屏环境)
    function initUI() {
        if (document.getElementById('skymusic-exporter-root')) return;

        const panel = document.createElement('div');
        panel.id = 'skymusic-exporter-root';
        panel.innerHTML = `
            <style>
                #skymusic-exporter-root {
                    position: fixed;
                    bottom: 12px;
                    right: 12px;
                    z-index: 9999999;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    max-width: 92vw;
                }
                .sky-export-card {
                    background: rgba(15, 23, 42, 0.94);
                    backdrop-filter: blur(12px);
                    -webkit-backdrop-filter: blur(12px);
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 12px;
                    padding: 8px 12px;
                    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
                    color: #fff;
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                    min-width: 260px;
                }
                .sky-card-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }
                .sky-header-left {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }
                .sky-status-dot {
                    width: 9px;
                    height: 9px;
                    border-radius: 50%;
                    background: #f59e0b;
                    box-shadow: 0 0 6px #f59e0b;
                    flex-shrink: 0;
                }
                .sky-status-dot.ready {
                    background: #10b981;
                    box-shadow: 0 0 8px #10b981;
                }
                .sky-badge {
                    font-size: 10px;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-weight: 700;
                }
                .sky-badge.downloaded {
                    background: rgba(16, 185, 129, 0.25);
                    color: #10b981;
                    border: 1px solid rgba(16, 185, 129, 0.5);
                }
                .sky-badge.not-downloaded {
                    background: rgba(245, 158, 11, 0.2);
                    color: #f59e0b;
                    border: 1px solid rgba(245, 158, 11, 0.4);
                }
                .sky-bridge-status {
                    font-size: 10px;
                    color: #38bdf8;
                    font-weight: 600;
                }
                .sky-title-area {
                    display: flex;
                    flex-direction: column;
                }
                .sky-title-area span {
                    font-size: 11px;
                    color: #94a3b8;
                    line-height: 1.3;
                }
                .sky-btn-group {
                    display: flex;
                    gap: 6px;
                    margin-top: 2px;
                }
                .sky-btn {
                    border: none;
                    outline: none;
                    cursor: pointer;
                    padding: 6px 8px;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 700;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 3px;
                    flex: 1;
                    transition: opacity 0.2s;
                }
                .sky-btn:active {
                    opacity: 0.75;
                }
                .sky-btn-play {
                    background: #f59e0b;
                    color: #000;
                    flex: 1.3;
                }
                .sky-btn-dl {
                    background: #10b981;
                    color: #fff;
                }
                .sky-btn-copy {
                    background: #3b82f6;
                    color: #fff;
                }
                .sky-btn:disabled {
                    opacity: 0.35;
                    cursor: not-allowed;
                }
            </style>
            <div class="sky-export-card">
                <div class="sky-card-header">
                    <div class="sky-header-left">
                        <div class="sky-status-dot" id="sky-dot"></div>
                        <strong style="font-size:12px;">光遇乐谱助手</strong>
                        <span class="sky-badge" id="sky-download-badge">浏览中</span>
                    </div>
                    <span class="sky-bridge-status">App直连 ✓</span>
                </div>
                <div class="sky-title-area">
                    <span id="sky-sub">点进乐谱详情页自动捕获数据</span>
                </div>
                <div class="sky-btn-group">
                    <button class="sky-btn sky-btn-play" id="sky-btn-play" disabled>▶ 立即弹奏</button>
                    <button class="sky-btn sky-btn-dl" id="sky-btn-dl" disabled>⬇️ 存入filesss</button>
                    <button class="sky-btn sky-btn-copy" id="sky-btn-copy" disabled>📋 复制JSON</button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);

        // 按钮 1：立即弹奏 (优先读本地，未有则自动保存至 filesss 并弹奏)
        document.getElementById('sky-btn-play').onclick = () => {
            const sid = getCurrentScoreId() || 0;
            const title = getCurrentTitle();
            const downloaded = isScoreDownloaded(sid, title);

            // 如果本地已经有，或者已捕获数据
            let jsonString = "";
            if (capturedScore) {
                const standardObj = formatToScoresFolderStandard(capturedScore);
                jsonString = JSON.stringify(standardObj);
            }

            if (!downloaded && !jsonString) {
                if (window.SkyMusicBridge) window.SkyMusicBridge.showToast('⏳ 正在加载乐谱数据，请稍候...');
                return;
            }

            if (window.SkyMusicBridge && typeof window.SkyMusicBridge.playScore === 'function') {
                window.SkyMusicBridge.playScore(sid, title, jsonString);
            }
        };

        // 按钮 2：仅存入 filesss 目录
        document.getElementById('sky-btn-dl').onclick = () => {
            if (!capturedScore) return;
            const sid = getCurrentScoreId() || 0;
            const title = getCurrentTitle();
            const standardObj = formatToScoresFolderStandard(capturedScore);
            const jsonString = JSON.stringify(standardObj);

            if (window.SkyMusicBridge && typeof window.SkyMusicBridge.saveScore === 'function') {
                window.SkyMusicBridge.saveScore(sid, title, jsonString);
            }
        };

        // 按钮 3：复制为弹琴轻量 JSON
        document.getElementById('sky-btn-copy').onclick = () => {
            if (!capturedScore) return;
            const standardObj = formatToScoresFolderStandard(capturedScore);
            const clipboardText = convertToSkyStudioClipboard(standardObj);

            if (window.SkyMusicBridge && typeof window.SkyMusicBridge.copyToClipboard === 'function') {
                window.SkyMusicBridge.copyToClipboard(clipboardText);
            } else {
                navigator.clipboard.writeText(clipboardText);
            }
        };

        updateStatusUI();
    }

    function updateStatusUI() {
        const sid = getCurrentScoreId();
        const title = getCurrentTitle();
        const badge = document.getElementById('sky-download-badge');
        const btnPlay = document.getElementById('sky-btn-play');
        const btnDl = document.getElementById('sky-btn-dl');
        const sub = document.getElementById('sky-sub');

        if (!badge || !btnPlay) return;

        const downloaded = isScoreDownloaded(sid, title);

        if (sid) {
            if (downloaded) {
                badge.innerText = '✓ 本地已下载';
                badge.className = 'sky-badge downloaded';
                btnPlay.innerText = '▶ 立即弹奏 (⚡秒播)';
                // 本地已有时，哪怕页面还没解密完成，也可以直接允许弹奏！
                btnPlay.disabled = false;
                if (!capturedScore && sub) {
                    sub.innerText = '本地已有此曲，可免下载直接弹奏';
                }
            } else {
                badge.innerText = '⏳ 本地未下载';
                badge.className = 'sky-badge not-downloaded';
                btnPlay.innerText = '▶ 下载并弹奏 (💾filesss)';
                if (!capturedScore) {
                    btnPlay.disabled = true;
                }
            }
        } else {
            badge.innerText = '浏览中';
            badge.className = 'sky-badge not-downloaded';
        }

        if (capturedScore) {
            btnDl.disabled = false;
            document.getElementById('sky-btn-copy').disabled = false;
            btnPlay.disabled = false;
        }
    }

    function onScoreReady() {
        const dot = document.getElementById('sky-dot');
        const sub = document.getElementById('sky-sub');
        if (!dot || !sub) return;

        const standard = formatToScoresFolderStandard(capturedScore);
        const score = standard.data.score;
        dot.classList.add('ready');
        sub.innerText = `《${score.metadata.title}》 (${score.noteCount}音符 / ${score.bpm} BPM)`;

        updateStatusUI();
    }

    // 暴露供 Android App 保存成功后回调刷新
    window.onScoreSavedFromApp = function (sid, title) {
        syncIndexFromApp();
        if (sid && !indexData.ids.includes(sid)) {
            indexData.ids.push(sid);
        }
        updateStatusUI();
        markScoreCardsOnList();
    };

    window.__skymusic_refresh = function () {
        syncIndexFromApp();
        updateStatusUI();
        markScoreCardsOnList();
    };

    // 监听单页应用 (SPA) 路由切换
    const origPushState = history.pushState;
    history.pushState = function (...args) {
        origPushState.apply(this, args);
        setTimeout(() => {
            capturedScore = null;
            syncIndexFromApp();
            updateStatusUI();
            markScoreCardsOnList();
        }, 200);
    };

    const origReplaceState = history.replaceState;
    history.replaceState = function (...args) {
        origReplaceState.apply(this, args);
        setTimeout(() => {
            syncIndexFromApp();
            updateStatusUI();
            markScoreCardsOnList();
        }, 200);
    };

    window.addEventListener('popstate', () => {
        setTimeout(() => {
            capturedScore = null;
            syncIndexFromApp();
            updateStatusUI();
            markScoreCardsOnList();
        }, 200);
    });

    // 页面轮询刷新列表标记
    setInterval(() => {
        markScoreCardsOnList();
    }, 2000);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initUI();
            markScoreCardsOnList();
        });
    } else {
        initUI();
        markScoreCardsOnList();
    }
})();
