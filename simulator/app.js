/**
 * SkyMusic 光遇 15 键弹琴模拟器与乐谱解析引擎
 */

// 1. Web Audio 光遇钢琴/竖琴音效合成器
class SkyAudioSynth {
  constructor() {
    this.ctx = null;
    // 15 个自然音阶对应的标准频率 (C4 ~ C6)
    this.frequencies = [
      261.63, // 0: C4 (Do)
      293.66, // 1: D4 (Re)
      329.63, // 2: E4 (Mi)
      349.23, // 3: F4 (Fa)
      392.00, // 4: G4 (Sol)
      440.00, // 5: A4 (La)
      493.88, // 6: B4 (Si)
      523.25, // 7: C5 (Do)
      587.33, // 8: D5 (Re)
      659.25, // 9: E5 (Mi)
      698.46, // 10: F5 (Fa)
      783.99, // 11: G5 (Sol)
      880.00, // 12: A5 (La)
      987.77, // 13: B5 (Si)
      1046.50 // 14: C6 (Do)
    ];
  }

  init() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  playKey(keyIndex, transpose = 0) {
    this.init();
    if (!this.ctx) return;

    const shiftedKey = keyIndex + transpose;
    if (shiftedKey < 0 || shiftedKey >= this.frequencies.length) return;

    const freq = this.frequencies[shiftedKey];
    const now = this.ctx.currentTime;

    // 光遇空灵钟琴双振荡器叠加 (正弦波基频 + 泛音)
    const osc1 = this.ctx.createOscillator();
    const osc2 = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(freq, now);

    osc2.type = 'triangle';
    osc2.frequency.setValueAtTime(freq * 2, now); // 高八度微弱泛音

    // 音量包络：极速敲击，柔和衰减 (光遇标志性泛音)
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.exponentialRampToValueAtTime(0.35, now + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.12, now + 0.2);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.2);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(this.ctx.destination);

    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 1.3);
    osc2.stop(now + 1.3);
  }
}

// 2. 屏幕布局自适应与校准管理器
class LayoutManager {
  constructor() {
    this.centerX = 0.50;
    this.centerY = 0.54;
    this.spacingX = 0.082;
    this.spacingY = 0.150;
    this.scale = 1.0;
  }

  setAspectRatioPreset(w, h) {
    const ratio = w / h;
    if (ratio >= 2.1) {
      this.centerX = 0.50; this.centerY = 0.55; this.spacingX = 0.076; this.spacingY = 0.155;
    } else if (ratio >= 1.9) {
      this.centerX = 0.50; this.centerY = 0.54; this.spacingX = 0.082; this.spacingY = 0.150;
    } else if (ratio >= 1.85) {
      this.centerX = 0.50; this.centerY = 0.54; this.spacingX = 0.086; this.spacingY = 0.152;
    } else if (ratio >= 1.7) {
      this.centerX = 0.50; this.centerY = 0.53; this.spacingX = 0.093; this.spacingY = 0.150;
    } else {
      this.centerX = 0.50; this.centerY = 0.52; this.spacingX = 0.110; this.spacingY = 0.135;
    }
    this.scale = 1.0;
  }

  getKeyPercentPosition(keyIndex) {
    const row = Math.floor(keyIndex / 5); // 0, 1, 2
    const col = keyIndex % 5;             // 0, 1, 2, 3, 4

    const dx = this.spacingX * this.scale;
    const dy = this.spacingY * this.scale;

    const x = this.centerX + (col - 2) * dx;
    const y = this.centerY + (row - 1) * dy;

    return { xPercent: x * 100, yPercent: y * 100 };
  }
}

// 3. 乐谱模型与解析器
const ScoreParsers = {
  parseSkyJson(content, defaultTitle = "JSON 乐谱") {
    let json;
    try {
      json = JSON.parse(content);
    } catch (e) {
      throw new Error("JSON 格式错误: " + e.message);
    }

    let targetObj = null;
    let songNotes = [];
    let title = defaultTitle;
    let bpm = 120;

    if (Array.isArray(json) && json.length > 0) {
      if (json[0].songNotes) {
        targetObj = json[0];
        songNotes = json[0].songNotes;
      } else if (json[0].time !== undefined) {
        songNotes = json;
      }
    } else if (json.songNotes) {
      targetObj = json;
      songNotes = json.songNotes;
    }

    if (targetObj) {
      if (targetObj.name) title = targetObj.name;
      if (targetObj.bpm) bpm = targetObj.bpm;
    }

    const timeMap = new Map();
    songNotes.forEach(item => {
      const time = item.time || 0;
      const keyStr = item.key || "";
      const match = keyStr.match(/Key(\d+)/i) || keyStr.match(/(\d+)/);
      if (match) {
        const keyIndex = parseInt(match[1], 10);
        if (keyIndex >= 0 && keyIndex <= 14) {
          if (!timeMap.has(time)) timeMap.set(time, []);
          const arr = timeMap.get(time);
          if (!arr.includes(keyIndex)) arr.push(keyIndex);
        }
      }
    });

    const notes = Array.from(timeMap.entries()).map(([t, keys]) => ({
      timeMs: t,
      keys: keys.sort((a, b) => a - b)
    })).sort((a, b) => a.timeMs - b.timeMs);

    const durationMs = notes.length ? notes[notes.length - 1].timeMs + 1000 : 0;

    return {
      id: "song_" + Date.now(),
      title: title,
      artist: "Sky 社区",
      bpm: bpm,
      notes: notes,
      durationMs: durationMs,
      type: "SkyJSON"
    };
  },

  parseMidi(arrayBuffer, filename = "MIDI 乐谱") {
    const data = new DataView(arrayBuffer);
    let offset = 0;

    // Check MThd
    const mthd = String.fromCharCode(data.getUint8(0), data.getUint8(1), data.getUint8(2), data.getUint8(3));
    if (mthd !== "MThd") throw new Error("非标准 MIDI 文件 (缺少 MThd)");

    offset = 8;
    const format = data.getUint16(offset);
    const numTracks = data.getUint16(offset + 2);
    const division = data.getUint16(offset + 4);
    const ppq = division > 0 ? division : 480;
    offset += 6;

    const rawNotes = [];
    const tempoChanges = [{ tick: 0, usPerQuarter: 500000 }];
    let title = filename.replace(/\.[^/.]+$/, "");

    for (let t = 0; t < numTracks && offset < data.byteLength; t++) {
      if (offset + 8 > data.byteLength) break;
      const trackId = String.fromCharCode(data.getUint8(offset), data.getUint8(offset+1), data.getUint8(offset+2), data.getUint8(offset+3));
      const trackLen = data.getUint32(offset + 4);
      offset += 8;
      const endPos = offset + trackLen;

      let currentTick = 0;
      let runningStatus = 0;

      while (offset < endPos && offset < data.byteLength) {
        // Read VLQ
        let delta = 0;
        let b;
        do {
          b = data.getUint8(offset++);
          delta = (delta << 7) | (b & 0x7F);
        } while (b & 0x80);
        currentTick += delta;

        let status = data.getUint8(offset++);
        if (status < 0x80) {
          status = runningStatus;
          offset--;
        } else {
          runningStatus = status;
        }

        if (status === 0xFF) {
          const metaType = data.getUint8(offset++);
          let metaLen = 0;
          do {
            b = data.getUint8(offset++);
            metaLen = (metaLen << 7) | (b & 0x7F);
          } while (b & 0x80);

          if (metaType === 0x03 && title === filename) {
            let name = "";
            for (let i = 0; i < metaLen; i++) name += String.fromCharCode(data.getUint8(offset + i));
            if (name.trim()) title = name.trim();
          } else if (metaType === 0x51 && metaLen >= 3) {
            const us = (data.getUint8(offset) << 16) | (data.getUint8(offset + 1) << 8) | data.getUint8(offset + 2);
            tempoChanges.push({ tick: currentTick, usPerQuarter: us });
          }
          offset += metaLen;
        } else if (status === 0xF0 || status === 0xF7) {
          let sysexLen = 0;
          do {
            b = data.getUint8(offset++);
            sysexLen = (sysexLen << 7) | (b & 0x7F);
          } while (b & 0x80);
          offset += sysexLen;
        } else {
          const type = status & 0xF0;
          if (type === 0x90) { // Note on
            const pitch = data.getUint8(offset++);
            const vel = data.getUint8(offset++);
            if (vel > 0) rawNotes.push({ tick: currentTick, pitch: pitch });
          } else if (type === 0x80 || type === 0xA0 || type === 0xB0 || type === 0xE0) {
            offset += 2;
          } else if (type === 0xC0 || type === 0xD0) {
            offset += 1;
          }
        }
      }
      offset = endPos;
    }

    // Tick to Millis
    tempoChanges.sort((a, b) => a.tick - b.tick);
    function tickToMs(targetTick) {
      let elapsedMs = 0;
      let curTick = 0;
      let curUs = tempoChanges[0].usPerQuarter;
      for (let i = 0; i < tempoChanges.length; i++) {
        if (targetTick <= tempoChanges[i].tick) break;
        const d = tempoChanges[i].tick - curTick;
        elapsedMs += (d * curUs) / (ppq * 1000);
        curTick = tempoChanges[i].tick;
        curUs = tempoChanges[i].usPerQuarter;
      }
      elapsedMs += ((targetTick - curTick) * curUs) / (ppq * 1000);
      return Math.round(elapsedMs);
    }

    // Sky 15-key pitch table (C4 to C6 diatonic)
    const SKY_PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84];
    const DIATONIC = new Set([0, 2, 4, 5, 7, 9, 11]);

    // Transposition fitting
    let bestShift = 0;
    let maxHits = -1;
    for (let s = -6; s <= 6; s++) {
      let hits = 0;
      for (const n of rawNotes) {
        if (DIATONIC.has(((n.pitch + s) % 12 + 12) % 12)) hits++;
      }
      if (hits > maxHits) {
        maxHits = hits;
        bestShift = s;
      }
    }

    // Octave shift to center on C5 (72)
    const pitches = rawNotes.map(n => n.pitch + bestShift).sort((a, b) => a - b);
    const median = pitches.length ? pitches[Math.floor(pitches.length / 2)] : 72;
    const octShift = Math.round((72 - median) / 12) * 12;

    const timeMap = new Map();
    rawNotes.forEach(n => {
      const ms = tickToMs(n.tick);
      const finalPitch = n.pitch + bestShift + octShift;

      // Find closest key
      let bestKey = 0;
      let minDiff = 999;
      for (let k = 0; k < SKY_PITCHES.length; k++) {
        const diff = Math.abs(finalPitch - SKY_PITCHES[k]);
        if (diff < minDiff) {
          minDiff = diff;
          bestKey = k;
        }
      }

      const qTime = Math.round(ms / 20) * 20; // 20ms quantize
      if (!timeMap.has(qTime)) timeMap.set(qTime, []);
      const arr = timeMap.get(qTime);
      if (!arr.includes(bestKey)) arr.push(bestKey);
    });

    const notes = Array.from(timeMap.entries()).map(([t, keys]) => ({
      timeMs: t,
      keys: keys.sort((a, b) => a - b)
    })).sort((a, b) => a.timeMs - b.timeMs);

    return {
      id: "midi_" + Date.now(),
      title: title,
      artist: "MIDI 自动转写",
      bpm: Math.round(60000000 / tempoChanges[0].usPerQuarter),
      notes: notes,
      durationMs: notes.length ? notes[notes.length - 1].timeMs + 1000 : 0,
      type: "MIDI"
    };
  }
};

// 4. 模拟器应用核心控制
class SkyMusicSimulator {
  constructor() {
    this.synth = new SkyAudioSynth();
    this.layout = new LayoutManager();
    this.songs = [];
    this.currentSong = null;

    this.isPlaying = false;
    this.playbackTimer = null;
    this.currentTimeMs = 0;
    this.speed = 1.0;
    this.transpose = 0;

    this.initDOM();
    this.loadDefaultPresets();
    this.renderPianoKeys();
    this.bindEvents();
  }

  initDOM() {
    this.phoneScreen = document.getElementById('phoneScreen');
    this.pianoBoard = document.getElementById('pianoBoard');
    this.floatingWidget = document.getElementById('floatingWidget');
    this.floatSongTitle = document.getElementById('floatSongTitle');
    this.progressBar = document.getElementById('progressBar');
    this.timeCurrent = document.getElementById('timeCurrent');
    this.timeTotal = document.getElementById('timeTotal');
    this.btnPlayPause = document.getElementById('btnPlayPause');
    this.speedVal = document.getElementById('speedVal');
    this.pitchVal = document.getElementById('pitchVal');
    this.songListContainer = document.getElementById('songListContainer');
    this.songCount = document.getElementById('songCount');
    this.ratioIndicator = document.getElementById('ratioIndicator');
  }

  loadDefaultPresets() {
    // 1. 小星星
    const twinkle = {
      id: "preset_twinkle",
      title: "小星星 (Twinkle Little Star)",
      artist: "经典儿歌 · 和弦伴奏",
      bpm: 120,
      type: "内置",
      durationMs: 16000,
      notes: [
        { timeMs: 0, keys: [0, 4] }, { timeMs: 500, keys: [0] },
        { timeMs: 1000, keys: [4, 7] }, { timeMs: 1500, keys: [4] },
        { timeMs: 2000, keys: [5, 7] }, { timeMs: 2500, keys: [5] },
        { timeMs: 3000, keys: [4, 0, 2] },
        { timeMs: 4000, keys: [3, 0] }, { timeMs: 4500, keys: [3] },
        { timeMs: 5000, keys: [2, 4] }, { timeMs: 5500, keys: [2] },
        { timeMs: 6000, keys: [1, 4] }, { timeMs: 6500, keys: [1] },
        { timeMs: 7000, keys: [0, 2, 4] },
        { timeMs: 8000, keys: [4, 0] }, { timeMs: 8500, keys: [4] },
        { timeMs: 9000, keys: [3, 1] }, { timeMs: 9500, keys: [3] },
        { timeMs: 10000, keys: [2, 0] }, { timeMs: 10500, keys: [2] },
        { timeMs: 11000, keys: [1, 4] },
        { timeMs: 12000, keys: [0, 4] }, { timeMs: 12500, keys: [0] },
        { timeMs: 13000, keys: [4, 7] }, { timeMs: 13500, keys: [4] },
        { timeMs: 14000, keys: [5, 7] }, { timeMs: 14500, keys: [5] },
        { timeMs: 15000, keys: [0, 4, 7] }
      ]
    };

    // 2. 千与千寻 永远同在
    const alwaysWithMe = {
      id: "preset_always",
      title: "千与千寻 - 永远同在",
      artist: "久石让 (Joe Hisaishi)",
      bpm: 96,
      type: "内置",
      durationMs: 14000,
      notes: [
        { timeMs: 0, keys: [2, 0] }, { timeMs: 380, keys: [3] },
        { timeMs: 760, keys: [4, 0] }, { timeMs: 1140, keys: [2] },
        { timeMs: 1520, keys: [0, 4] }, { timeMs: 1900, keys: [7] },
        { timeMs: 2280, keys: [6, 1] }, { timeMs: 2660, keys: [4] },
        { timeMs: 3040, keys: [5, 0] }, { timeMs: 3420, keys: [4] },
        { timeMs: 3800, keys: [3, 5] }, { timeMs: 4180, keys: [2] },
        { timeMs: 4560, keys: [1, 4] }, { timeMs: 4940, keys: [2] },
        { timeMs: 5320, keys: [3, 0] }, { timeMs: 5700, keys: [1] },
        { timeMs: 6080, keys: [2, 0] }, { timeMs: 6460, keys: [3] },
        { timeMs: 6840, keys: [4, 0] }, { timeMs: 7220, keys: [7] },
        { timeMs: 7600, keys: [8, 1] }, { timeMs: 7980, keys: [7] },
        { timeMs: 8360, keys: [6, 4] }, { timeMs: 8740, keys: [5] },
        { timeMs: 9120, keys: [4, 0, 2] }
      ]
    };

    // 3. 天空之城
    const castle = {
      id: "preset_castle",
      title: "天空之城 (Laputa)",
      artist: "久石让",
      bpm: 88,
      type: "内置",
      durationMs: 12000,
      notes: [
        { timeMs: 0, keys: [5] }, { timeMs: 350, keys: [6] },
        { timeMs: 700, keys: [7, 0] }, { timeMs: 1050, keys: [6] },
        { timeMs: 1400, keys: [7] }, { timeMs: 1750, keys: [9, 2] },
        { timeMs: 2450, keys: [6, 4] }, { timeMs: 3150, keys: [2] },
        { timeMs: 3500, keys: [5] }, { timeMs: 3850, keys: [4, 0] },
        { timeMs: 4200, keys: [5] }, { timeMs: 4550, keys: [7] },
        { timeMs: 4900, keys: [4, 2] }, { timeMs: 5600, keys: [2, 0] },
        { timeMs: 6300, keys: [1] }, { timeMs: 6650, keys: [2] },
        { timeMs: 7000, keys: [3] }, { timeMs: 7350, keys: [4, 0] },
        { timeMs: 7700, keys: [3] }, { timeMs: 8050, keys: [4] },
        { timeMs: 8400, keys: [7, 2] }, { timeMs: 9100, keys: [2, 4] },
        { timeMs: 9800, keys: [0, 4, 7] }
      ]
    };

    // 4. 卡农
    const canon = {
      id: "preset_canon",
      title: "卡农 (Canon in D)",
      artist: "帕赫贝尔",
      bpm: 110,
      type: "内置",
      durationMs: 13000,
      notes: [
        { timeMs: 0, keys: [9, 0] }, { timeMs: 320, keys: [8] },
        { timeMs: 640, keys: [7, 4] }, { timeMs: 960, keys: [6] },
        { timeMs: 1280, keys: [5, 5] }, { timeMs: 1600, keys: [4] },
        { timeMs: 1920, keys: [5, 2] }, { timeMs: 2240, keys: [6] },
        { timeMs: 2560, keys: [7, 0] }, { timeMs: 2880, keys: [8] },
        { timeMs: 3200, keys: [9, 4] }, { timeMs: 3520, keys: [8] },
        { timeMs: 3840, keys: [7, 5] }, { timeMs: 4160, keys: [6] },
        { timeMs: 4480, keys: [5, 2] }, { timeMs: 4800, keys: [4] },
        { timeMs: 5120, keys: [2, 0, 4, 7] }
      ]
    };

    this.songs = [twinkle, alwaysWithMe, castle, canon];
    this.selectSong(twinkle);
    this.renderSongList();
  }

  renderPianoKeys() {
    this.pianoBoard.innerHTML = '';
    const noteLabels = [
      "1", "2", "3", "4", "5",
      "6", "7", "+1", "+2", "+3",
      "+4", "+5", "+6", "+7", "++1"
    ];

    for (let i = 0; i < 15; i++) {
      const keyEl = document.createElement('div');
      keyEl.className = 'sky-key';
      keyEl.id = `key_${i}`;
      keyEl.dataset.key = i;

      const pos = this.layout.getKeyPercentPosition(i);
      keyEl.style.left = `${pos.xPercent}%`;
      keyEl.style.top = `${pos.yPercent}%`;

      const innerEl = document.createElement('div');
      innerEl.className = 'sky-key-inner';
      innerEl.textContent = noteLabels[i];
      keyEl.appendChild(innerEl);

      // 支持鼠标直接点击按键弹琴与发声
      keyEl.addEventListener('pointerdown', () => {
        this.triggerKeyVisual(i);
        this.synth.playKey(i, this.transpose);
      });

      this.pianoBoard.appendChild(keyEl);
    }
  }

  updateKeyPositions() {
    for (let i = 0; i < 15; i++) {
      const keyEl = document.getElementById(`key_${i}`);
      if (keyEl) {
        const pos = this.layout.getKeyPercentPosition(i);
        keyEl.style.left = `${pos.xPercent}%`;
        keyEl.style.top = `${pos.yPercent}%`;
      }
    }
  }

  triggerKeyVisual(keyIndex) {
    const keyEl = document.getElementById(`key_${keyIndex}`);
    if (keyEl) {
      keyEl.classList.add('active');
      setTimeout(() => {
        keyEl.classList.remove('active');
      }, 90);
    }
  }

  selectSong(song) {
    this.stopPlayback();
    this.currentSong = song;
    this.floatSongTitle.textContent = song.title;
    this.timeTotal.textContent = this.formatTime(song.durationMs);
    this.timeCurrent.textContent = "00:00";
    this.progressBar.value = 0;
    this.renderSongList();
  }

  renderSongList() {
    this.songListContainer.innerHTML = '';
    this.songCount.textContent = `${this.songs.length} 首曲目`;

    this.songs.forEach(song => {
      const item = document.createElement('div');
      item.className = `song-item ${this.currentSong && this.currentSong.id === song.id ? 'selected' : ''}`;

      const totalNotes = song.notes.reduce((acc, cur) => acc + cur.keys.length, 0);

      item.innerHTML = `
        <div class="song-meta-left">
          <div class="song-name">${song.title}</div>
          <div class="song-sub">${totalNotes} 音符 · ${this.formatTime(song.durationMs)} · ${song.bpm} BPM</div>
        </div>
        <span class="song-tag">${song.type}</span>
      `;

      item.addEventListener('click', () => {
        this.selectSong(song);
        this.startPlayback();
      });

      this.songListContainer.appendChild(item);
    });
  }

  // -------------------------------------------------------------
  // 播放引擎逻辑
  // -------------------------------------------------------------
  togglePlayPause() {
    if (this.isPlaying) {
      this.pausePlayback();
    } else {
      this.startPlayback();
    }
  }

  startPlayback() {
    if (!this.currentSong || !this.currentSong.notes.length) return;
    this.synth.init();
    this.isPlaying = true;
    this.btnPlayPause.textContent = "⏸";

    const song = this.currentSong;
    let nextNoteIdx = song.notes.findIndex(n => n.timeMs >= this.currentTimeMs);
    if (nextNoteIdx === -1) {
      this.currentTimeMs = 0;
      nextNoteIdx = 0;
    }

    let lastTimestamp = performance.now();

    const loop = (now) => {
      if (!this.isPlaying) return;

      const deltaRealMs = now - lastTimestamp;
      lastTimestamp = now;

      // 根据倍速换算乐曲时间
      this.currentTimeMs += deltaRealMs * this.speed;

      // 触发当前时刻前所有未触发的音符
      while (nextNoteIdx < song.notes.length && song.notes[nextNoteIdx].timeMs <= this.currentTimeMs) {
        const note = song.notes[nextNoteIdx];
        note.keys.forEach(k => {
          this.triggerKeyVisual(k);
          this.synth.playKey(k, this.transpose);
        });
        nextNoteIdx++;
      }

      // 更新进度
      this.timeCurrent.textContent = this.formatTime(this.currentTimeMs);
      const percent = Math.min(1000, Math.round((this.currentTimeMs / song.durationMs) * 1000));
      this.progressBar.value = percent;

      if (this.currentTimeMs >= song.durationMs || nextNoteIdx >= song.notes.length) {
        this.stopPlayback();
        return;
      }

      this.playbackTimer = requestAnimationFrame(loop);
    };

    this.playbackTimer = requestAnimationFrame(loop);
  }

  pausePlayback() {
    this.isPlaying = false;
    cancelAnimationFrame(this.playbackTimer);
    this.btnPlayPause.textContent = "▶";
  }

  stopPlayback() {
    this.pausePlayback();
    this.currentTimeMs = 0;
    this.progressBar.value = 0;
    this.timeCurrent.textContent = "00:00";
  }

  seekTo(targetMs) {
    const wasPlaying = this.isPlaying;
    this.pausePlayback();
    this.currentTimeMs = targetMs;
    this.timeCurrent.textContent = this.formatTime(targetMs);
    if (wasPlaying) {
      this.startPlayback();
    }
  }

  formatTime(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  }

  // -------------------------------------------------------------
  // 事件绑定与用户交互
  // -------------------------------------------------------------
  bindEvents() {
    // 播放按钮
    this.btnPlayPause.addEventListener('click', () => this.togglePlayPause());
    document.getElementById('btnStop').addEventListener('click', () => this.stopPlayback());

    // 切歌
    document.getElementById('btnPrev').addEventListener('click', () => {
      const idx = this.songs.findIndex(s => s.id === this.currentSong.id);
      const nextIdx = (idx - 1 + this.songs.length) % this.songs.length;
      this.selectSong(this.songs[nextIdx]);
      this.startPlayback();
    });
    document.getElementById('btnNext').addEventListener('click', () => {
      const idx = this.songs.findIndex(s => s.id === this.currentSong.id);
      const nextIdx = (idx + 1) % this.songs.length;
      this.selectSong(this.songs[nextIdx]);
      this.startPlayback();
    });

    // 进度条拖拽
    this.progressBar.addEventListener('input', (e) => {
      if (!this.currentSong) return;
      const targetMs = (e.target.value / 1000) * this.currentSong.durationMs;
      this.seekTo(targetMs);
    });

    // 倍速调节
    document.getElementById('btnSpeedDown').addEventListener('click', () => {
      this.speed = Math.max(0.5, this.speed - 0.25);
      this.speedVal.textContent = `${this.speed.toFixed(2)}x`;
    });
    document.getElementById('btnSpeedUp').addEventListener('click', () => {
      this.speed = Math.min(2.5, this.speed + 0.25);
      this.speedVal.textContent = `${this.speed.toFixed(2)}x`;
    });

    // 移调调节
    document.getElementById('btnPitchDown').addEventListener('click', () => {
      this.transpose -= 1;
      this.pitchVal.textContent = this.transpose > 0 ? `+${this.transpose}` : `${this.transpose}`;
    });
    document.getElementById('btnPitchUp').addEventListener('click', () => {
      this.transpose += 1;
      this.pitchVal.textContent = this.transpose > 0 ? `+${this.transpose}` : `${this.transpose}`;
    });

    // 悬浮窗最小化/还原
    const btnMini = document.getElementById('btnMinimizeFloat');
    btnMini.addEventListener('click', (e) => {
      e.stopPropagation();
      this.floatingWidget.classList.add('minimized');
    });
    this.floatingWidget.addEventListener('click', (e) => {
      if (this.floatingWidget.classList.contains('minimized')) {
        this.floatingWidget.classList.remove('minimized');
      }
    });

    // 屏幕比例预设切换
    const chips = document.querySelectorAll('.preset-resolutions .btn-chip');
    chips.forEach(chip => {
      chip.addEventListener('click', () => {
        chips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');

        const w = parseInt(chip.dataset.w, 10);
        const h = parseInt(chip.dataset.h, 10);
        const name = chip.dataset.name;

        this.phoneScreen.style.aspectRatio = `${w} / ${h}`;
        this.ratioIndicator.textContent = `屏幕比例: ${name} (${w} × ${h})`;

        this.layout.setAspectRatioPreset(w, h);
        this.syncSlidersFromLayout();
        this.updateKeyPositions();
      });
    });

    // 校准滑块
    document.getElementById('sliderCenterY').addEventListener('input', (e) => {
      this.layout.centerY = e.target.value / 100;
      this.updateKeyPositions();
    });
    document.getElementById('sliderSpacingX').addEventListener('input', (e) => {
      this.layout.spacingX = e.target.value / 1000;
      this.updateKeyPositions();
    });
    document.getElementById('sliderSpacingY').addEventListener('input', (e) => {
      this.layout.spacingY = e.target.value / 1000;
      this.updateKeyPositions();
    });
    document.getElementById('sliderScale').addEventListener('input', (e) => {
      this.layout.scale = e.target.value / 100;
      this.updateKeyPositions();
    });

    document.getElementById('btnResetLayout').addEventListener('click', () => {
      this.layout.setAspectRatioPreset(2400, 1080);
      this.syncSlidersFromLayout();
      this.updateKeyPositions();
    });

    // 文件导入监听 (MIDI / JSON / TXT)
    const fileInput = document.getElementById('fileInput');
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const lower = file.name.toLowerCase();
      const reader = new FileReader();

      if (lower.endsWith('.mid') || lower.endsWith('.midi')) {
        reader.onload = (ev) => {
          try {
            const parsed = ScoreParsers.parseMidi(ev.target.result, file.name);
            this.songs.unshift(parsed);
            this.selectSong(parsed);
            this.startPlayback();
            alert(`成功导入 MIDI 乐谱《${parsed.title}》！`);
          } catch (err) {
            alert("解析 MIDI 失败: " + err.message);
          }
        };
        reader.readAsArrayBuffer(file);
      } else {
        reader.onload = (ev) => {
          try {
            const parsed = ScoreParsers.parseSkyJson(ev.target.result, file.name);
            this.songs.unshift(parsed);
            this.selectSong(parsed);
            this.startPlayback();
            alert(`成功导入 Sky JSON 乐谱《${parsed.title}》！`);
          } catch (err) {
            alert("解析乐谱文件失败: " + err.message);
          }
        };
        reader.readAsText(file);
      }
    });

    // 弹窗帮助
    const helpModal = document.getElementById('helpModal');
    document.getElementById('btnToggleHelp').addEventListener('click', () => {
      helpModal.classList.add('show');
    });
    document.getElementById('btnCloseHelp').addEventListener('click', () => {
      helpModal.classList.remove('show');
    });
    helpModal.addEventListener('click', (e) => {
      if (e.target === helpModal) helpModal.classList.remove('show');
    });
  }

  syncSlidersFromLayout() {
    document.getElementById('sliderCenterY').value = Math.round(this.layout.centerY * 100);
    document.getElementById('sliderSpacingX').value = Math.round(this.layout.spacingX * 1000);
    document.getElementById('sliderSpacingY').value = Math.round(this.layout.spacingY * 1000);
    document.getElementById('sliderScale').value = Math.round(this.layout.scale * 100);
  }
}

// 页面加载就绪后启动模拟器
window.addEventListener('DOMContentLoaded', () => {
  window.simulator = new SkyMusicSimulator();
});
