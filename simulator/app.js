/**
 * SkyMusic 光遇 15 键弹琴模拟器与乐谱解析引擎
 */

// 1. Web Audio 光遇大钢琴物理声学合成引擎 (光遇高保真大三角钢琴音色)
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

    // 高保真钢琴采样缓存表 (物理声学建模预渲染)
    this.sampleCache = new Map();
    this.masterCompressor = null;
    this.dryGain = null;
    this.reverbConvolver = null;
    this.wetGain = null;
    this.isPreheating = false;
  }

  init() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx();
      this.setupMasterAudioChain();
      this.preheatPresets();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  setupMasterAudioChain() {
    // 1. 动态范围压限器：防止快速和弦或多声部重叠时破音/爆音
    this.masterCompressor = this.ctx.createDynamicsCompressor();
    this.masterCompressor.threshold.setValueAtTime(-16, this.ctx.currentTime);
    this.masterCompressor.knee.setValueAtTime(12, this.ctx.currentTime);
    this.masterCompressor.ratio.setValueAtTime(3.5, this.ctx.currentTime);
    this.masterCompressor.attack.setValueAtTime(0.003, this.ctx.currentTime);
    this.masterCompressor.release.setValueAtTime(0.18, this.ctx.currentTime);
    this.masterCompressor.connect(this.ctx.destination);

    // 2. 直达声音量总线
    this.dryGain = this.ctx.createGain();
    this.dryGain.gain.setValueAtTime(0.85, this.ctx.currentTime);
    this.dryGain.connect(this.masterCompressor);

    // 3. 光遇专属空灵大厅 / 琴房声学混响总线 (立体声脉冲卷积混响)
    try {
      this.reverbConvolver = this.ctx.createConvolver();
      this.reverbConvolver.buffer = this.buildReverbImpulse(1.6, 2.2);
      this.wetGain = this.ctx.createGain();
      this.wetGain.gain.setValueAtTime(0.25, this.ctx.currentTime);
      this.reverbConvolver.connect(this.wetGain);
      this.wetGain.connect(this.masterCompressor);
    } catch (e) {
      console.warn("混响卷积初始化降级:", e);
      this.reverbConvolver = null;
    }
  }

  // 生成温暖通透的遇境大殿/木质共鸣箱立体声混响脉冲
  buildReverbImpulse(duration = 1.6, decay = 2.2) {
    const sampleRate = this.ctx.sampleRate || 44100;
    const length = Math.floor(duration * sampleRate);
    const impulse = this.ctx.createBuffer(2, length, sampleRate);
    const left = impulse.getChannelData(0);
    const right = impulse.getChannelData(1);

    for (let i = 0; i < length; i++) {
      const t = i / sampleRate;
      const env = Math.exp(-decay * t);
      left[i] = (Math.random() * 2 - 1) * env;
      right[i] = (Math.random() * 2 - 1) * env;
    }

    // 模拟木质材料的高频阻尼吸收滤波
    let lpL = 0, lpR = 0;
    const alpha = 0.28;
    for (let i = 0; i < length; i++) {
      lpL += alpha * (left[i] - lpL);
      lpR += alpha * (right[i] - lpR);
      left[i] = lpL;
      right[i] = lpR;
    }

    return impulse;
  }

  // 物理声学建模：合成真实大钢琴琴弦与共鸣箱敲击波形
  synthesizePianoSample(freq) {
    const sampleRate = this.ctx ? this.ctx.sampleRate : 44100;
    // 低音延音长，高音衰减快 (C4约3.2秒，C6约2.0秒)
    const duration = Math.min(3.4, Math.max(1.8, 3.2 / Math.pow(freq / 261.63, 0.35)));
    const N = Math.floor(duration * sampleRate);
    const buffer = this.ctx.createBuffer(1, N, sampleRate);
    const out = buffer.getChannelData(0);

    // 1. 刚性琴弦非谐波系数 (Inharmonicity B factor, 钢琴特有的清亮微拉伸倍频)
    const B = 0.00018 * Math.pow(freq / 261.63, 0.45);

    // 2. 真实大三角钢琴泛音振幅分布 (基频 + 12个泛音列)
    const harmonicWeights = [
      0,
      1.00,  // 1: 基频
      0.68,  // 2: 八度
      0.44,  // 3: 十二度 (五度)
      0.30,  // 4: 双八度
      0.19,  // 5: 双八度加三度
      0.12,  // 6: 双八度加五度
      0.075, // 7: 双八度加小七度
      0.048, // 8: 三八度
      0.030, // 9
      0.018, // 10
      0.010, // 11
      0.005  // 12
    ];

    const baseSustain = duration * 0.95;

    // 3. 弦组同音弦微调耦合 (Trichord Detuning: 3根琴弦微小失谐干涉产生的丰满合唱与缓拍)
    for (let k = 1; k < harmonicWeights.length; k++) {
      const amp = harmonicWeights[k];
      const partialFreq = k * freq * Math.sqrt(1 + B * k * k);
      if (partialFreq > sampleRate * 0.46) break;

      // 高频泛音能量耗散衰减速度远快于低频基音 (钢琴标志性的音色明亮 -> 温暖圆润演化)
      const decayRate = (1.0 / baseSustain) * (1.0 + 0.33 * (k - 1) + 0.036 * (k - 1) * (k - 1));

      let detunes, weights;
      if (k <= 3) {
        detunes = [1.0, 1.0008, 0.9992];
        weights = [0.44, 0.28, 0.28];
      } else if (k <= 6) {
        detunes = [1.0004, 0.9996];
        weights = [0.5, 0.5];
      } else {
        detunes = [1.0];
        weights = [1.0];
      }

      for (let s = 0; s < detunes.length; s++) {
        const f = partialFreq * detunes[s];
        const w = (2 * Math.PI * f) / sampleRate;
        const cosW = Math.cos(w), sinW = Math.sin(w);
        const strW = weights[s] * amp;

        let r = 1.0, im = 0.0;
        const stepDecay = Math.exp(-decayRate / sampleRate);
        let curAmp = strW;

        for (let i = 0; i < N; i++) {
          const nr = r * cosW - im * sinW;
          const nim = r * sinW + im * cosW;
          r = nr; im = nim;
          out[i] += curAmp * r;
          curAmp *= stepDecay;
        }
      }
    }

    // 4. 钢琴毛毡琴槌敲击瞬态与共鸣板木质冲击 (Hammer Strike & Soundboard Thump)
    for (let i = 0; i < N; i++) {
      const t = i / sampleRate;
      if (t > 0.07) break;
      // 琴槌毛毡撞击杂音 (接触摩擦衰减)
      const feltNoise = (Math.random() * 2 - 1) * Math.exp(-t * 240) * 0.28;
      // 木质琴板与琴桥低频共振冲击 (~140 Hz)
      const knock = Math.sin(2 * Math.PI * 140 * t) * Math.exp(-t * 85) * 0.38;
      // 钢弦击点瞬态高频碰触音 (~3000 Hz)
      const strike = Math.sin(2 * Math.PI * 3000 * t) * Math.exp(-t * 320) * 0.20;
      out[i] += (feltNoise + knock + strike) * 0.32;
    }

    // 5. 毫秒级防爆音平滑击键曲线 (2.0ms 击键启动)
    const attackSamples = Math.floor(0.002 * sampleRate);
    for (let i = 0; i < attackSamples; i++) {
      out[i] *= (i / attackSamples);
    }

    // 6. 物理双阶段衰减 (Prompt Sound 能量骤放 + Singing Sustain 悠长吟唱)
    for (let i = 0; i < N; i++) {
      const t = i / sampleRate;
      out[i] *= (1.0 + 0.45 * Math.exp(-t * 22));
    }

    // 7. 标准化增益 (防止单音过载，保持音量一致且动态充沛)
    let peak = 0;
    for (let i = 0; i < N; i++) {
      if (Math.abs(out[i]) > peak) peak = Math.abs(out[i]);
    }
    if (peak > 0) {
      const normGain = 0.84 / peak;
      for (let i = 0; i < N; i++) {
        out[i] *= normGain;
      }
    }

    return buffer;
  }

  // 获取或实时预渲染单音缓存
  getAudioBuffer(freq) {
    const key = Math.round(freq * 100) / 100;
    if (!this.sampleCache.has(key)) {
      const buf = this.synthesizePianoSample(freq);
      this.sampleCache.set(key, buf);
    }
    return this.sampleCache.get(key);
  }

  // 异步预热预加载 15 个钢琴常用键，确保弹奏与播放时 0 延迟、0 卡顿
  preheatPresets() {
    if (this.isPreheating) return;
    this.isPreheating = true;
    let idx = 0;
    const scheduleNext = () => {
      if (idx >= this.frequencies.length) return;
      this.getAudioBuffer(this.frequencies[idx]);
      idx++;
      if ('requestIdleCallback' in window) {
        window.requestIdleCallback(scheduleNext, { timeout: 100 });
      } else {
        setTimeout(scheduleNext, 16);
      }
    };
    scheduleNext();
  }

  // 播放单音：支持 15 键键盘、移调与多声部自然复音
  playKey(keyIndex, transpose = 0) {
    this.init();
    if (!this.ctx) return;

    // 调性偏移计算
    const shiftedKey = keyIndex + transpose;
    let freq;
    if (shiftedKey >= 0 && shiftedKey < this.frequencies.length) {
      freq = this.frequencies[shiftedKey];
    } else {
      // 超出 15 键范围时优雅推导自然音高，避免按键哑音
      const baseFreq = this.frequencies[Math.max(0, Math.min(14, keyIndex))];
      freq = baseFreq * Math.pow(2, transpose / 7);
    }

    const now = this.ctx.currentTime;
    const buffer = this.getAudioBuffer(freq);

    // 音频源节点
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;

    // 单音独立包络控制器
    const voiceGain = this.ctx.createGain();
    voiceGain.gain.setValueAtTime(0.9, now);

    // 大钢琴 88 键声场自然立体声微展宽 (左低音 -> 右高音)
    if (this.ctx.createStereoPanner) {
      const panner = this.ctx.createStereoPanner();
      const panValue = -0.22 + (Math.max(0, Math.min(14, keyIndex)) / 14) * 0.44;
      panner.pan.setValueAtTime(panValue, now);

      source.connect(voiceGain);
      voiceGain.connect(panner);

      panner.connect(this.dryGain);
      if (this.reverbConvolver) {
        panner.connect(this.reverbConvolver);
      }
    } else {
      source.connect(voiceGain);
      voiceGain.connect(this.dryGain);
      if (this.reverbConvolver) {
        voiceGain.connect(this.reverbConvolver);
      }
    }

    source.start(now);
  }
}

// 2. 屏幕布局自适应与校准管理器
class LayoutManager {
  constructor() {
    this.centerX = 0.475; // 往左微调5下: 0.50 -> 0.475
    this.centerY = 0.440; // 往上微调20下: 0.54 -> 0.440
    this.spacingX = 0.082;
    this.spacingY = 0.150;
    this.scale = 1.09;    // 放大3下: 1.00 -> 1.09
  }

  setAspectRatioPreset(w, h) {
    const ratio = w / h;
    if (ratio >= 2.1) {
      this.centerX = 0.475; this.centerY = 0.450; this.spacingX = 0.076; this.spacingY = 0.155;
    } else if (ratio >= 1.9) {
      this.centerX = 0.475; this.centerY = 0.440; this.spacingX = 0.082; this.spacingY = 0.150;
    } else if (ratio >= 1.85) {
      this.centerX = 0.475; this.centerY = 0.440; this.spacingX = 0.086; this.spacingY = 0.152;
    } else if (ratio >= 1.7) {
      this.centerX = 0.475; this.centerY = 0.430; this.spacingX = 0.093; this.spacingY = 0.150;
    } else {
      this.centerX = 0.475; this.centerY = 0.420; this.spacingX = 0.110; this.spacingY = 0.135;
    }
    this.scale = 1.09;
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
          if (runningStatus === 0) break;
          status = runningStatus;
          offset--;
        } else {
          runningStatus = status < 0xF0 ? status : 0;
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
          const channel = status & 0x0F;
          if (type === 0x90) { // Note on
            const pitch = data.getUint8(offset++);
            const vel = data.getUint8(offset++);
            // 过滤 Channel 9 (第10轨道打击乐/鼓点)
            if (vel > 0 && channel !== 9) {
              rawNotes.push({ tick: currentTick, pitch: pitch });
            }
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

    // Krumhansl-Schmuckler 调性检测矩阵
    const MAJOR_PROF = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88];
    const MINOR_PROF = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17];

    const counts = new Array(12).fill(0);
    rawNotes.forEach(n => { counts[((n.pitch % 12) + 12) % 12]++; });

    function pearson(x, y) {
      const n = 12;
      let sx = 0, sy = 0;
      for (let i = 0; i < n; i++) { sx += x[i]; sy += y[i]; }
      const mx = sx / n, my = sy / n;
      let num = 0, dx = 0, dy = 0;
      for (let i = 0; i < n; i++) {
        const vx = x[i] - mx, vy = y[i] - my;
        num += vx * vy;
        dx += vx * vx;
        dy += vy * vy;
      }
      const den = Math.sqrt(dx * dy);
      return den === 0 ? 0 : num / den;
    }

    let bestScore = -999;
    let bestShift = 0;
    for (let tonic = 0; tonic < 12; tonic++) {
      const rot = Array.from({ length: 12 }, (_, i) => counts[(tonic + i) % 12]);
      const sMaj = pearson(rot, MAJOR_PROF);
      const sMin = pearson(rot, MINOR_PROF);
      if (sMaj > bestScore) {
        bestScore = sMaj;
        let s = (12 - tonic) % 12;
        if (s > 6) s -= 12;
        bestShift = s;
      }
      if (sMin > bestScore) {
        bestScore = sMin;
        let s = (9 - tonic) % 12;
        if (s > 6) s -= 12;
        bestShift = s;
      }
    }

    // 备用白键匹配
    const testHits = rawNotes.filter(n => DIATONIC.has(((n.pitch + bestShift) % 12 + 12) % 12)).length;
    if (rawNotes.length > 0 && testHits / rawNotes.length < 0.70) {
      let maxH = -1;
      for (let s = -6; s <= 6; s++) {
        const h = rawNotes.filter(n => DIATONIC.has(((n.pitch + s) % 12 + 12) % 12)).length;
        if (h > maxH) { maxH = h; bestShift = s; }
      }
    }

    // 计算最佳基准八度偏移 (-24, -12, 0, 12, 24)
    const transposedPitches = rawNotes.map(n => n.pitch + bestShift);
    let bestOct = 0;
    let maxInRange = -1;
    [-24, -12, 0, 12, 24].forEach(oct => {
      const cnt = transposedPitches.filter(p => (p + oct) >= 60 && (p + oct) <= 84).length;
      if (cnt > maxInRange) {
        maxInRange = cnt;
        bestOct = oct;
      }
    });

    const timeMap = new Map();
    rawNotes.forEach(n => {
      const ms = tickToMs(n.tick);
      let p = n.pitch + bestShift + bestOct;

      // 智能八度循环折叠 (Octave Folding)
      while (p < 60) p += 12;
      while (p > 84) p -= 12;

      // 映射到 15 键
      let bestKey = 0;
      let minDiff = 999;
      for (let k = 0; k < SKY_PITCHES.length; k++) {
        const diff = Math.abs(p - SKY_PITCHES[k]);
        if (diff < minDiff) {
          minDiff = diff;
          bestKey = k;
          if (diff === 0) break;
        }
      }

      // 30ms 时间窗聚合和弦
      const qTime = Math.round(ms / 30) * 30;
      if (!timeMap.has(qTime)) timeMap.set(qTime, []);
      const arr = timeMap.get(qTime);
      if (!arr.includes(bestKey)) arr.push(bestKey);
    });

    // 和弦声部精炼 (上限 4 键，保留旋律与低音)
    const notes = Array.from(timeMap.entries()).map(([t, rawKeys]) => {
      const sorted = Array.from(new Set(rawKeys)).sort((a, b) => a - b);
      let keys = sorted;
      if (sorted.length > 4) {
        keys = [sorted[0], sorted[sorted.length - 1]];
        const mid = sorted.slice(1, sorted.length - 1);
        if (mid.length === 1) keys.push(mid[0]);
        else if (mid.length >= 2) { keys.push(mid[0]); keys.push(mid[mid.length - 1]); }
        keys = Array.from(new Set(keys)).sort((a, b) => a - b);
      }
      return { timeMs: t, keys: keys };
    }).sort((a, b) => a.timeMs - b.timeMs);

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
