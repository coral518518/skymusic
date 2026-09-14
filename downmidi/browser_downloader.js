/**
 * 爱给网 (Aigei) 音频全自动批量提取与下载脚本
 * 
 * 使用方法：
 * 1. 在浏览器（Chrome/Edge等）中打开爱给网歌曲列表页面（如 https://www.aigei.com/music/midi/）
 * 2. 按 F12 打开开发者工具，切换到 "Console"（控制台）标签页
 * 3. 复制本文件的全部代码，粘贴到控制台并按回车（Enter）
 * 4. 页面右下角会出现一个精致的控制面板，点击【开始提取并下载】即可！
 */

(function() {
    'use strict';

    // 避免重复注入
    if (window._AIGEIDownloaderInjected) {
        if (window._AIGEIDownloaderUI) {
            window._AIGEIDownloaderUI.style.display = 'block';
        }
        console.log('[爱给网下载器] 脚本已在运行中，已恢复界面。');
        return;
    }
    window._AIGEIDownloaderInjected = true;

    // 状态管理
    const state = {
        isRunning: false,
        isPaused: false,
        currentIndex: 0,
        songs: [],
        results: [],
        downloadDelay: 1200, // 每首歌之间的间隔（毫秒），防风控
        currentResolver: null
    };

    // 1. 扫描页面中所有的歌曲卡片
    function scanSongs() {
        const items = document.querySelectorAll('.audio-item-box');
        const list = [];
        items.forEach((item, index) => {
            const itemId = item.getAttribute('itemid') || item.getAttribute('itembox') || '';
            const titleEl = item.querySelector('.title-name') || item.querySelector('.title');
            let title = titleEl ? titleEl.innerText.trim() : `音频_${itemId}`;
            // 净化文件名
            title = title.replace(/[\r\n\t]/g, ' ').replace(/[\\/:*?"<>|]/g, '_').trim();
            // 截断过长标题
            if (title.length > 50) title = title.substring(0, 50);

            const input = item.querySelector('input[id^="itemInfoToken_"]') || item.querySelector('input[ftype]');
            const playBtn = item.querySelector('.audio-player-btn');

            if (itemId && input) {
                list.push({
                    index: index + 1,
                    itemId: itemId,
                    title: title,
                    inputEl: input,
                    playBtn: playBtn,
                    cardEl: item,
                    url: null,
                    ext: 'mp3',
                    status: 'pending'
                });
            }
        });
        return list;
    }

    // 2. Hook 全局音频播放回调，捕获真实直链
    const originalCallBack = window.callBackAudioFilePlay;
    window.callBackAudioFilePlay = function(R, G, C, t) {
        try {
            let resData = G;
            if (typeof G === 'string') {
                try { resData = JSON.parse(G); } catch(e) {}
            }
            if (resData && resData.url) {
                const capturedUrl = resData.url;
                if (state.currentResolver) {
                    state.currentResolver(capturedUrl);
                }
            }
        } catch (err) {
            console.error('[爱给网下载器] 回调解析异常:', err);
        }

        // 调用原回调，保持系统正常运转
        if (typeof originalCallBack === 'function') {
            try {
                // 如果在批量提取中，静音处理避免噪音
                return originalCallBack.apply(this, arguments);
            } catch(e) {}
        }
    };

    // 3. 提取单首歌曲的真实直链
    function fetchSongUrl(song) {
        return new Promise((resolve) => {
            let resolved = false;
            const timer = setTimeout(() => {
                if (!resolved) {
                    resolved = true;
                    state.currentResolver = null;
                    resolve(null);
                }
            }, 6000); // 6秒超时

            state.currentResolver = (url) => {
                if (!resolved) {
                    resolved = true;
                    clearTimeout(timer);
                    state.currentResolver = null;
                    resolve(url);
                }
            };

            // 优先直接调用官方接口 fileGet 解析
            try {
                if (typeof window.fileGet === 'function') {
                    window.fileGet(song.inputEl, 'play', null, null, null, null, { itemId: song.itemId });
                } else if (song.playBtn) {
                    // 降级为模拟点击播放按钮
                    song.playBtn.click();
                } else {
                    resolved = true;
                    clearTimeout(timer);
                    resolve(null);
                }
            } catch (e) {
                console.warn('[爱给网下载器] fileGet 触发失败，尝试模拟点击:', e);
                if (song.playBtn) song.playBtn.click();
            }
        });
    }

    // 4. 文件下载触发器
    function triggerDownload(url, filename) {
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.target = '_blank';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => document.body.removeChild(a), 500);
    }

    // 5. 导出文本列表和 JSON
    function exportFiles() {
        if (state.results.length === 0) {
            alert('暂无已提取的链接可导出！');
            return;
        }

        // 导出 txt 链接列表
        let txtContent = "# 爱给网音频下载链接清单\n# 格式：歌曲序号. 歌名 -> 下载直链\n\n";
        state.results.forEach(r => {
            if (r.url) {
                txtContent += `${r.filename}\t${r.url}\n`;
            }
        });
        const txtBlob = new Blob([txtContent], { type: 'text/plain;charset=utf-8' });
        triggerDownload(URL.createObjectURL(txtBlob), `aigei_download_links_${Date.now()}.txt`);

        // 导出 json 详细清单
        const jsonBlob = new Blob([JSON.stringify(state.results, null, 2)], { type: 'application/json;charset=utf-8' });
        setTimeout(() => {
            triggerDownload(URL.createObjectURL(jsonBlob), `aigei_songs_metadata_${Date.now()}.json`);
        }, 300);
    }

    // 6. 主执行循环
    async function startBatch(autoDownload = true) {
        if (state.isRunning) return;
        state.isRunning = true;
        state.isPaused = false;
        btnStart.disabled = true;
        btnExportOnly.disabled = true;
        btnPause.disabled = false;
        btnPause.innerText = '⏸ 暂停';

        // 刷新列表
        state.songs = scanSongs();
        updateUI();

        log(`开始处理，共发现 ${state.songs.length} 首歌曲...`, '#4ade80');

        for (let i = state.currentIndex; i < state.songs.length; i++) {
            if (!state.isRunning) break;
            while (state.isPaused) {
                await new Promise(r => setTimeout(r, 500));
            }

            state.currentIndex = i;
            const song = state.songs[i];
            const numPrefix = String(i + 1).padStart(2, '0');
            log(`[${i + 1}/${state.songs.length}] 正在提取: ${song.title}...`);
            updateUI();

            // 获取直链
            let url = await fetchSongUrl(song);

            // 判断扩展名
            let ext = 'mp3';
            if (url) {
                if (url.includes('.mid') || url.includes('.midi')) ext = 'mid';
                else if (url.includes('.mp3')) ext = 'mp3';
            }

            const filename = `${numPrefix}. ${song.title}.${ext}`;

            if (url) {
                song.url = url;
                song.ext = ext;
                song.status = 'success';
                state.results.push({
                    index: i + 1,
                    itemId: song.itemId,
                    title: song.title,
                    filename: filename,
                    ext: ext,
                    url: url
                });
                log(`✔ 成功获取: ${song.title} (${ext})`, '#38bdf8');

                if (autoDownload) {
                    triggerDownload(url, filename);
                }
            } else {
                song.status = 'failed';
                log(`✖ 获取失败: ${song.title}`, '#f87171');
            }

            updateUI();

            // 防风控防封间隔
            await new Promise(r => setTimeout(r, state.downloadDelay));
        }

        state.isRunning = false;
        btnStart.disabled = false;
        btnExportOnly.disabled = false;
        btnPause.disabled = true;
        log('🎉 全部任务处理完成！', '#a855f7');
        
        // 自动导出清单备份
        if (state.results.length > 0) {
            exportFiles();
        }
    }

    // 7. 构建现代 UI 悬浮面板
    const container = document.createElement('div');
    container.id = 'aigei-downloader-panel';
    container.innerHTML = `
        <div style="
            position: fixed;
            bottom: 24px;
            right: 24px;
            width: 380px;
            background: rgba(18, 24, 38, 0.95);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 16px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            font-size: 13px;
            z-index: 9999999;
            padding: 18px;
            box-sizing: border-box;
            transition: all 0.3s ease;
        ">
            <!-- 头部 -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">🎵</span>
                    <strong style="font-size: 15px; letter-spacing: 0.5px;">爱给网音频批量下载器</strong>
                </div>
                <button id="ag-btn-close" style="background: none; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; padding: 0 4px;">✕</button>
            </div>

            <!-- 统计信息 -->
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 14px; text-align: center;">
                <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 8px;">
                    <div style="color: #94a3b8; font-size: 11px;">检测到歌曲</div>
                    <div id="ag-stat-total" style="font-size: 16px; font-weight: bold; color: #38bdf8;">0</div>
                </div>
                <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 8px;">
                    <div style="color: #94a3b8; font-size: 11px;">成功抓取</div>
                    <div id="ag-stat-success" style="font-size: 16px; font-weight: bold; color: #4ade80;">0</div>
                </div>
                <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 8px;">
                    <div style="color: #94a3b8; font-size: 11px;">进度</div>
                    <div id="ag-stat-percent" style="font-size: 16px; font-weight: bold; color: #fbbf24;">0%</div>
                </div>
            </div>

            <!-- 进度条 -->
            <div style="background: rgba(255,255,255,0.1); height: 6px; border-radius: 3px; overflow: hidden; margin-bottom: 14px;">
                <div id="ag-progress-bar" style="background: linear-gradient(90deg, #38bdf8, #818cf8); height: 100%; width: 0%; transition: width 0.2s;"></div>
            </div>

            <!-- 实时日志窗 -->
            <div id="ag-log-box" style="
                background: rgba(0, 0, 0, 0.4);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 8px;
                height: 110px;
                padding: 8px 10px;
                overflow-y: auto;
                font-family: Consolas, monospace;
                font-size: 11px;
                line-height: 1.5;
                margin-bottom: 14px;
                color: #cbd5e1;
            ">
                <div style="color: #94a3b8;">[就绪] 等待点击操作...</div>
            </div>

            <!-- 操作按钮组 -->
            <div style="display: flex; flex-direction: column; gap: 8px;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                    <button id="ag-btn-start" style="
                        background: linear-gradient(135deg, #0284c7, #2563eb);
                        color: white;
                        border: none;
                        padding: 9px 12px;
                        border-radius: 8px;
                        font-weight: 600;
                        cursor: pointer;
                        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
                        transition: opacity 0.2s;
                    ">🚀 开始提取并下载</button>
                    <button id="ag-btn-export-only" style="
                        background: rgba(255, 255, 255, 0.1);
                        color: #f8fafc;
                        border: 1px solid rgba(255, 255, 255, 0.2);
                        padding: 9px 12px;
                        border-radius: 8px;
                        font-weight: 600;
                        cursor: pointer;
                        transition: background 0.2s;
                    ">📋 仅提取并导出</button>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                    <button id="ag-btn-pause" disabled style="
                        background: rgba(255, 255, 255, 0.05);
                        color: #94a3b8;
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        padding: 7px 10px;
                        border-radius: 8px;
                        cursor: pointer;
                    ">⏸ 暂停</button>
                    <button id="ag-btn-export-now" style="
                        background: rgba(255, 255, 255, 0.05);
                        color: #94a3b8;
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        padding: 7px 10px;
                        border-radius: 8px;
                        cursor: pointer;
                    ">💾 导出已抓取列表</button>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(container);
    window._AIGEIDownloaderUI = container;

    // DOM 元素引用
    const statTotal = document.getElementById('ag-stat-total');
    const statSuccess = document.getElementById('ag-stat-success');
    const statPercent = document.getElementById('ag-stat-percent');
    const progressBar = document.getElementById('ag-progress-bar');
    const logBox = document.getElementById('ag-log-box');
    const btnStart = document.getElementById('ag-btn-start');
    const btnExportOnly = document.getElementById('ag-btn-export-only');
    const btnPause = document.getElementById('ag-btn-pause');
    const btnExportNow = document.getElementById('ag-btn-export-now');
    const btnClose = document.getElementById('ag-btn-close');

    function log(msg, color = '#cbd5e1') {
        const item = document.createElement('div');
        item.style.color = color;
        item.innerText = msg;
        logBox.appendChild(item);
        logBox.scrollTop = logBox.scrollHeight;
    }

    function updateUI() {
        const total = state.songs.length;
        const current = state.currentIndex;
        const success = state.results.length;
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;

        statTotal.innerText = total;
        statSuccess.innerText = success;
        statPercent.innerText = `${percent}%`;
        progressBar.style.width = `${percent}%`;
    }

    // 事件绑定
    btnStart.onclick = () => startBatch(true);
    btnExportOnly.onclick = () => startBatch(false);
    btnPause.onclick = () => {
        state.isPaused = !state.isPaused;
        btnPause.innerText = state.isPaused ? '▶ 继续' : '⏸ 暂停';
        log(state.isPaused ? '已暂停' : '已继续执行...', '#fbbf24');
    };
    btnExportNow.onclick = () => exportFiles();
    btnClose.onclick = () => {
        container.style.display = 'none';
        console.log('[爱给网下载器] 面板已隐藏。如需再次显示，请在控制台执行：window._AIGEIDownloaderUI.style.display="block"');
    };

    // 初始化扫描
    state.songs = scanSongs();
    statTotal.innerText = state.songs.length;
    log(`初始化完成，发现本页共 ${state.songs.length} 首歌曲！`);
    console.log(`%c[爱给网批量下载器] 加载成功！本页共发现 ${state.songs.length} 首歌曲。`, 'color: #38bdf8; font-weight: bold; font-size: 14px;');
})();
