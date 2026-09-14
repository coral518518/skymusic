#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer & Arranger) V7 原曲高保真版
================================================================================
核心目标：
  【100% 还原原曲主旋律！让人在光遇中第一耳朵就能听出是什么歌！】

本版本针对“听不出是什么歌”、“旋律被伴奏碎音打乱”、“被拖入低音区发闷发沉”等
核心痛点进行了全方位的声学与乐理再重构：

  1. 光遇黄金演唱音域 (C4~C6, 60~84) 默认基准：
     - 光遇 15 键物理发音与主流工具 (Sky Studio / AutoSky) 默认基准为 C4~C6；
     - 彻底摒弃把流行歌曲强行拖拽下潜至 C3~C5 (48~72) 低音大提琴音区导致的“闷沉发浑”；
     - 让真人歌唱音域 (60~81) 完美舒展在光遇琴键的正中央，明亮清透，原汁原味！

  2. 纯净人声歌唱流提取 (Vocal Stream Segregation & Trough Filtering)：
     - 精准提取最高天际线旋律；
     - 自动识别人声换气停顿 (Vocal Rests) 中吉他/钢琴弹奏的低音扫弦与过门琶音伪音，
       坚决剔除低音干扰，绝不让伴奏碎音插进歌词中间，确保歌词线条如流水般连贯！

  3. 神经转录泛音谐波还原 (Harmonic Normalization)：
     - 自动识别音频转录中飙升至 >= 84 (C6 以上) 的人声二次泛音谐波，
       平滑降维归位至真实人声高音区 (72~76)，彻底攻克副歌高潮断崖坠落的顽疾！

  4. 真实歌唱时值保护与同音连击吐字 (Lyrical Phrasing & Articulation)：
     - 确立最小歌唱时值保障 (>= 1/4 拍)，坚决杜绝把歌声截断成 30ms 机械杂音的毛刺感；
     - 旋律连音 (Legato) 平滑连贯，同音连击保留微弱吐字气口，歌词字句颗粒饱满、清晰如歌。

  5. 纯净温润强拍低音 (Sparse & Warm Downbeat Bass)：
     - 伴奏仅在小节强拍保留极轻柔的低音根音 (力度 52~58)，为主旋律提供沉稳的和声地基；
     - 主旋律响亮突出 (力度 102)，主次层次分明，绝不喧宾夺主。

  6. 多格式导出与安全保存：
     - 光遇 Clean MIDI、15 键字母谱 (A1~C5)、中式标准数字简谱 (1 2 3 4 5 6 7)；
     - Windows 播放器占用文件时自动避让保存，永不闪退。
================================================================================
"""

import os
import sys
import math
import argparse
from collections import defaultdict
from statistics import mean, median

# Windows 控制台 UTF-8 支持
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import mido


# ==============================================================================
# 音乐常数与光遇 15 键定义
# ==============================================================================

WHITE_PITCH_CLASSES = {0, 2, 4, 5, 7, 9, 11}
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler 调式能量剖面
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# 光遇 15 键黄金音高定义 (基准 C4=60 到 C6=84，光遇游戏/Sky Studio/AutoSky 标准)
SKY_KEYS_C4 = [
    60, 62, 64, 65, 67, 69, 71,
    72, 74, 76, 77, 79, 81, 83,
    84,
]

# 光遇 15 键低音八度 (基准 C3=48 到 C5=72)
SKY_KEYS_C3 = [
    48, 50, 52, 53, 55, 57, 59,
    60, 62, 64, 65, 67, 69, 71,
    72,
]

# 光遇 3x5 经典按键坐标名称
SKY_KEY_TAGS = [
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
    "C1", "C2", "C3", "C4", "C5",
]

# 中式标准数字简谱对应表 (以中央 C=60 为中音 1，C5=72 为高音 1'，C6=84 为倍高音 1'')
DEGREE_MAP_C4 = {
    60: "1",  62: "2",  64: "3",  65: "4",  67: "5",  69: "6",  71: "7",
    72: "1'", 74: "2'", 76: "3'", 77: "4'", 79: "5'", 81: "6'", 83: "7'",
    84: "1''",
}

# 低音区对应表 (C3~B3: 48~59)
DEGREE_MAP_C3 = {
    48: "1.", 50: "2.", 52: "3.", 53: "4.", 55: "5.", 57: "6.", 59: "7.",
    60: "1",  62: "2",  64: "3",  65: "4",  67: "5",  69: "6",  71: "7",
    72: "1'",
}


# ==============================================================================
# 第一步：音符事件解析与原曲主旋律提取 (Acoustic Parsing & Vocal Extraction)
# ==============================================================================

class NoteEvent:
    __slots__ = ("pitch", "start", "dur", "end", "velocity", "track", "channel", "is_melody")

    def __init__(self, pitch, start, dur, velocity=80, track=0, channel=0, is_melody=False):
        self.pitch = pitch
        self.start = start
        self.dur = max(1, dur)
        self.end = start + self.dur
        self.velocity = velocity
        self.track = track
        self.channel = channel
        self.is_melody = is_melody

    def __repr__(self):
        role = "Mel" if self.is_melody else "Acc"
        return f"Note({role}, P={self.pitch}, T={self.start}~{self.end})"


def parse_midi_file(mid_path):
    """解析 MIDI 文件，提取有效音符（自动过滤 Channel 10 打击乐）"""
    mid = mido.MidiFile(mid_path)
    tpb = mid.ticks_per_beat

    bpm = 120.0
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                bpm = mido.tempo2bpm(msg.tempo)
                break
        if bpm != 120.0:
            break

    tracks_notes = []

    for trk_idx, track in enumerate(mid.tracks):
        current_tick = 0
        active_notes = {}
        notes = []
        name = f"Track_{trk_idx}"

        for msg in track:
            current_tick += msg.time
            if msg.type == "track_name":
                name = msg.name.strip()
            elif msg.type in ("note_on", "note_off"):
                channel = getattr(msg, "channel", 0)
                pitch = getattr(msg, "note", None)
                if pitch is None or channel == 9:  # 过滤 Drum
                    continue

                key = (channel, pitch)
                vel = getattr(msg, "velocity", 0)

                if msg.type == "note_on" and vel > 0:
                    if key in active_notes:
                        old = active_notes.pop(key)
                        dur = current_tick - old["start"]
                        if dur > 0:
                            notes.append(NoteEvent(pitch, old["start"], dur, old["velocity"], trk_idx, channel))
                    active_notes[key] = {"start": current_tick, "velocity": vel}
                else:
                    if key in active_notes:
                        old = active_notes.pop(key)
                        dur = current_tick - old["start"]
                        if dur > 0:
                            notes.append(NoteEvent(pitch, old["start"], dur, old["velocity"], trk_idx, channel))

        fallback_dur = max(tpb // 4, 1)
        for (channel, pitch), old in active_notes.items():
            dur = max(fallback_dur, current_tick - old["start"])
            notes.append(NoteEvent(pitch, old["start"], dur, old["velocity"], trk_idx, channel))

        if notes:
            notes.sort(key=lambda n: (n.start, n.pitch))
            tracks_notes.append((trk_idx, name, notes))

    return tracks_notes, tpb, bpm


def evaluate_melody_track(notes, name=""):
    """多轨 MIDI 音轨旋律专业评分"""
    if not notes:
        return -9999.0

    name_lower = name.lower()
    keyword_bonus = 0.0
    for kw in ("vocal", "melody", "lead", "solo", "flute", "violin", "singer", "right", "主旋律", "唱"):
        if kw in name_lower:
            keyword_bonus += 40.0
    for kw in ("bass", "drum", "percussion", "chord", "pad", "accomp", "left", "伴奏", "低音"):
        if kw in name_lower:
            keyword_bonus -= 40.0

    pitches = [n.pitch for n in notes]
    avg_pitch = mean(pitches)
    pitch_range = max(pitches) - min(pitches)

    onset_counts = defaultdict(int)
    for n in notes:
        onset_counts[n.start] += 1
    polyphony_rate = sum(1 for c in onset_counts.values() if c > 1) / max(1, len(onset_counts))

    score = 0.0
    # 人声演唱黄金中高音区 (60~76)
    if 62 <= avg_pitch <= 78:
        score += 30.0
    else:
        score -= abs(avg_pitch - 70) * 1.0

    score -= polyphony_rate * 40.0

    if 10 <= pitch_range <= 30:
        score += 15.0
    else:
        score -= abs(pitch_range - 18) * 0.5

    score += min(len(notes) * 0.05, 15.0)
    score += keyword_bonus
    return score


def extract_pure_melody_and_accompaniment(tracks_notes, tpb):
    """
    原曲高保真主旋律抽取核心算法：
    1. 多轨清晰时：自动锁定主旋律音轨；
    2. 单轨或混音轨时：
       - 天际线聚类提取最高歌唱声部；
       - 人声泛音倍频修正 (>= 84 降维至 72~76)；
       - 【关键】：剔除人声停顿换气处吉他/钢琴插进来的低音扫弦与琶音伪音；
       - 确保歌词主旋律 100% 完整连贯，人人都能第一耳朵听出原曲！
    """
    all_notes = []
    for trk_idx, name, notes in tracks_notes:
        all_notes.extend(notes)

    if not all_notes:
        return [], []

    all_notes.sort(key=lambda n: (n.start, n.pitch))

    # 多轨判定
    if len(tracks_notes) > 1:
        scored_tracks = []
        for trk_idx, name, notes in tracks_notes:
            s = evaluate_melody_track(notes, name)
            scored_tracks.append((s, trk_idx, name, notes))
        scored_tracks.sort(key=lambda x: x[0], reverse=True)

        best_score, best_trk_idx, best_name, melody_candidates = scored_tracks[0]

        if best_score >= 15.0 and len(melody_candidates) >= 20:
            # 找到明确的主旋律音轨
            melody_notes = []
            for n in melody_candidates:
                p = n.pitch
                while p >= 84:
                    p -= 12
                melody_notes.append(NoteEvent(p, n.start, n.dur, n.velocity, n.track, n.channel, is_melody=True))
            
            melody_keys = {(n.start, n.pitch) for n in melody_notes}
            accomp_notes = [n for n in all_notes if (n.start, n.pitch) not in melody_keys]
            return melody_notes, accomp_notes

    # 单轨/音频转录谱：听觉流分离与伪音过滤
    ordered = sorted(all_notes, key=lambda n: (n.start, -n.pitch))
    onset_window = max(10, tpb // 16)
    clusters = []
    current_cluster = [ordered[0]]

    for n in ordered[1:]:
        if n.start - current_cluster[0].start <= onset_window:
            current_cluster.append(n)
        else:
            clusters.append(current_cluster)
            current_cluster = [n]
    if current_cluster:
        clusters.append(current_cluster)

    raw_skyline = []
    accomp_pool = []

    for cluster in clusters:
        top_note = max(cluster, key=lambda x: x.pitch)
        # 修正转录人声泛音倍频
        p = top_note.pitch
        while p >= 84:
            p -= 12
        top_note.pitch = p

        raw_skyline.append(top_note)
        for n in cluster:
            if n != top_note:
                accomp_pool.append(n)

    # 计算旋律的音高分布特征
    sky_pitches = [n.pitch for n in raw_skyline]
    p_med = median(sky_pitches) if sky_pitches else 69

    # 【核心乐理过滤】：剔除歌手歌词换气停顿处插进来的吉他/钢琴分解低音琶音
    cleaned_melody = []
    for i, n in enumerate(raw_skyline):
        p = n.pitch
        # 如果音符明显跌入低音伴奏区 (< 60 或比旋律中位数低 8 个半音以上)
        if p < 60:
            accomp_pool.append(n)
            continue
        if p < 64 and p < p_med - 7:
            prev_p = raw_skyline[i - 1].pitch if i > 0 else p
            next_p = raw_skyline[i + 1].pitch if i + 1 < len(raw_skyline) else p
            # 前后都在人声演唱区，当前音孤立下跌，必是伴奏扫弦伪音
            if prev_p >= 64 and next_p >= 64:
                accomp_pool.append(n)
                continue

        n.is_melody = True
        cleaned_melody.append(n)

    if len(cleaned_melody) < 20:
        cleaned_melody = [n for n in all_notes if n.pitch >= 60]
        for n in cleaned_melody:
            n.is_melody = True

    return cleaned_melody, accomp_pool


def shape_legato_melody(melody_notes, tpb):
    """
    歌唱旋律连音平滑与时值保护：
    1. 最小发音时值保障：杜绝 30ms 抽搐碎音，确保每个音符有足够的起振与延音共鸣；
    2. 歌唱连音平滑 (Legato)：缝合微小转录间隙，歌声流动如歌；
    3. 同音连击吐字气口：同音反复时保留微弱吐字气隙，使快歌字句颗粒分明、节奏感极强。
    """
    if not melody_notes:
        return []

    sorted_notes = sorted(melody_notes, key=lambda n: (n.start, -n.pitch))
    min_dur = max(tpb // 4, 45)  # 至少 1/4 拍或 45 ticks，确保可听清音高与歌词
    repeat_gap = max(18, tpb // 16)  # 同音连击吐字微气隙

    monophonic = []
    for n in sorted_notes:
        dur = max(n.dur, min_dur)
        if not monophonic:
            monophonic.append(NoteEvent(n.pitch, n.start, dur, n.velocity, n.track, n.channel, is_melody=True))
            continue

        prev = monophonic[-1]

        # 时序发生重叠碰撞：截断前一音
        if n.start < prev.end:
            if prev.pitch == n.pitch:
                prev.dur = max(min_dur, n.start - prev.start - repeat_gap)
            else:
                prev.dur = max(min_dur, n.start - prev.start)
            prev.end = prev.start + prev.dur

        # 歌唱连音平滑缝合
        gap = n.start - prev.end
        if 0 < gap <= int(tpb * 0.28):
            if prev.pitch != n.pitch:
                prev.dur = n.start - prev.start
                prev.end = n.start

        monophonic.append(NoteEvent(n.pitch, n.start, dur, n.velocity, n.track, n.channel, is_melody=True))

    return monophonic


# ==============================================================================
# 第二步：调性识别与全曲最佳移调 (Key Detection & White Key Alignment)
# ==============================================================================

def pearson_correlation(a, b):
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma)**2 for x in a) * sum((y - mb)**2 for y in b))
    return num / den if den != 0 else 0.0


def detect_key_and_mode(melody_notes):
    """K-S 算法精准测定调性与调式"""
    if not melody_notes:
        return "C", "major", 0

    hist = [0.0] * 12
    for n in melody_notes:
        hist[n.pitch % 12] += 1.0

    best_tonic = 0
    best_mode = "major"
    best_r = -1.0

    for tonic in range(12):
        rot = hist[tonic:] + hist[:tonic]
        r_maj = pearson_correlation(rot, MAJOR_PROFILE)
        r_min = pearson_correlation(rot, MINOR_PROFILE)

        if r_maj > best_r:
            best_r = r_maj
            best_tonic = tonic
            best_mode = "major"
        if r_min > best_r:
            best_r = r_min
            best_tonic = tonic
            best_mode = "minor"

    tonic_name = NOTE_NAMES[best_tonic]
    return tonic_name, best_mode, best_tonic


def find_optimal_sky_transposition(melody_notes, sky_keys):
    """
    寻找最大化保留原曲音高、让旋律完美落在光遇 15 键上的最佳移调：
    1. 半音移调 k in [-5, 6]：将歌曲调性完美对齐全白键；
    2. 八度偏移 oct_s：在目标音域内居中，优先确保原音高不产生大跌！
    """
    if not melody_notes:
        return 0, 0, 0, 0.0

    target_min = min(sky_keys)
    target_max = max(sky_keys)

    # 1. 寻找白键吻合率最高的移调量 k
    best_k = 0
    max_white = -1

    for k in range(-5, 7):
        white_count = sum(1 for n in melody_notes if (n.pitch + k) % 12 in WHITE_PITCH_CLASSES)
        if white_count > max_white:
            max_white = white_count
            best_k = k

    white_rate = max_white / max(1, len(melody_notes))

    # 2. 寻找最佳八度平移 oct_shift
    # 评价标准：让尽可能多的音符直接落在 [target_min, target_max] 内，惩罚越界
    best_oct = 0
    best_in_range = -1
    lowest_penalty = float("inf")

    for oct_s in [0, -1, 1, -2, 2]:
        shift = best_k + oct_s * 12
        in_range = 0
        penalty = 0.0

        for n in melody_notes:
            p = n.pitch + shift
            if target_min <= p <= target_max:
                in_range += 1
            elif p > target_max:
                penalty += (p - target_max) * 8.0
            elif p < target_min:
                penalty += (target_min - p) * 6.0

        # 优先选择落在音区内音符最多、惩罚最低的八度
        score = -in_range * 10.0 + penalty
        if score < lowest_penalty:
            lowest_penalty = score
            best_oct = oct_s
            best_in_range = in_range

    total_shift = best_k + best_oct * 12
    return best_k, best_oct, total_shift, white_rate


# ==============================================================================
# 第三步：音程保真 Viterbi 动态规划 (Direction-Preserving Viterbi DP)
# ==============================================================================

def map_melody_sequence_dp(melody_notes, total_shift, sky_keys):
    """
    基于 Viterbi 动态规划的音程保真映射：
    - 严禁粗暴数值截断；
    - 代价函数重度惩罚旋律走向反转，确保歌曲旋律辨识度 100% 保持！
    """
    if not melody_notes:
        return []

    target_min = min(sky_keys)
    target_max = max(sky_keys)
    sky_keys_set = set(sky_keys)

    def get_candidates(raw_p):
        folded = raw_p
        while folded < target_min:
            folded += 12
        while folded > target_max:
            folded -= 12

        cands = set()
        if folded in sky_keys_set:
            cands.add(folded)

        # 针对边界外 1 个半音的音符，提供平滑级进候选
        if raw_p == target_min - 1:
            cands.add(target_min)
        elif raw_p == target_max + 1:
            cands.add(target_max)

        # 离调黑键取相邻白键
        for k in sky_keys:
            if abs(k - folded) == 1:
                cands.add(k)

        if not cands:
            cands.add(min(sky_keys, key=lambda p: abs(p - folded)))

        return sorted(cands)

    raw_pitches = [n.pitch + total_shift for n in melody_notes]
    candidates = [get_candidates(rp) for rp in raw_pitches]

    dp = []
    back = []

    for i, cand_list in enumerate(candidates):
        row = [float("inf")] * len(cand_list)
        row_b = [-1] * len(cand_list)

        for ci, mp in enumerate(cand_list):
            diff = abs(mp - raw_pitches[i]) % 12
            diff = min(diff, 12 - diff)
            loc_cost = 0.0 if diff == 0 else (1.5 if diff == 1 else 5.0)

            if i == 0:
                row[ci] = loc_cost
                continue

            for pi, pmp in enumerate(candidates[i - 1]):
                raw_interval = raw_pitches[i] - raw_pitches[i - 1]
                map_interval = mp - pmp

                trans = abs(map_interval - raw_interval) * 3.0

                # 走向反转惩罚（最影响歌曲听觉辨识度的关键）
                if raw_interval > 0 and map_interval < 0:
                    trans += 18.0
                elif raw_interval < 0 and map_interval > 0:
                    trans += 18.0

                if raw_interval == 0 and map_interval != 0:
                    trans += 8.0

                if abs(map_interval) >= 12:
                    trans += 8.0

                total_cost = dp[i - 1][pi] + loc_cost + trans
                if total_cost < row[ci]:
                    row[ci] = total_cost
                    row_b[ci] = pi

        dp.append(row)
        back.append(row_b)

    best_idx = min(range(len(dp[-1])), key=lambda i: dp[-1][i])
    mapped_pitches = [0] * len(melody_notes)

    for i in range(len(melody_notes) - 1, -1, -1):
        mapped_pitches[i] = candidates[i][best_idx]
        best_idx = back[i][best_idx]

    mapped_melody = []
    for n, mp in zip(melody_notes, mapped_pitches):
        mapped_melody.append(NoteEvent(mp, n.start, n.dur, n.velocity, n.track, n.channel, is_melody=True))

    return mapped_melody


# ==============================================================================
# 第四步：纯净伴奏架构与网格量化 (Clean Bass & Quantization)
# ==============================================================================

def choose_rhythm_grid(notes, tpb):
    """自适应选择音乐律动网格 (优先 1/16 或 1/8 拍)"""
    if len(notes) < 4:
        return max(1, tpb // 4)

    starts = sorted(set(n.start for n in notes))
    candidates = [max(1, tpb // 4), max(1, tpb // 2)]
    candidates = list(dict.fromkeys(candidates))

    best_grid = candidates[0]
    best_score = float("inf")

    for grid in candidates:
        errors = [abs(x - int(round(x / grid) * grid)) for x in starts]
        m_err = mean(errors)
        ex_r = sum(1 for e in errors if e == 0) / len(errors)
        sc = m_err - ex_r * 4.0
        if sc < best_score:
            best_score = sc
            best_grid = grid

    return best_grid


def snap_grid(val, grid):
    return int(round(val / grid) * grid)


def build_sparse_strong_beat_bass(accomp_notes, total_shift, mapped_melody, sky_keys, tpb, grid):
    """
    小节强拍极简低音伴奏：
    - 伴奏仅在每小节强拍 (Downbeat) 保留单个深沉根音；
    - 伴奏音高固定在光遇低音区 (A1~A5)，力度轻柔 (55)；
    - 伴奏与主旋律音高严格错开，绝不在同一高度撞音；
    - 构成干净、空灵、烘托主旋律的光遇双声部。
    """
    if not accomp_notes or not mapped_melody:
        return []

    target_min = min(sky_keys)
    bass_ceiling = target_min + 11  # 伴奏严格限制在第一排 (A1~A5)
    min_bass_interval = tpb * 2     # 至少相隔两拍

    melody_by_time = {snap_grid(m.start, grid): m.pitch for m in mapped_melody}
    accomp_by_time = defaultdict(list)

    for n in accomp_notes:
        p = n.pitch + total_shift
        while p < target_min:
            p += 12
        while p > bass_ceiling:
            p -= 12

        if p not in sky_keys:
            p = min(sky_keys, key=lambda vk: abs(vk - p))

        t = snap_grid(n.start, grid)
        accomp_by_time[t].append((p, n))

    anchored_bass = []
    last_bass_time = -999999

    for t in sorted(accomp_by_time.keys()):
        if t - last_bass_time < min_bass_interval:
            continue

        beat_offset = min(t % tpb, tpb - (t % tpb))
        if beat_offset > grid * 1.5:
            continue

        candidates = accomp_by_time[t]
        candidates.sort(key=lambda x: x[0])
        best_p, raw_n = candidates[0]

        concur_mel = melody_by_time.get(t)
        if concur_mel is not None:
            # 伴奏必须低于主旋律
            if best_p >= concur_mel:
                if best_p - 12 >= target_min:
                    best_p -= 12
                else:
                    continue
            # 避让同音或严重刺耳半音
            if abs(concur_mel - best_p) in (0, 1):
                continue

        if target_min <= best_p <= bass_ceiling:
            dur = max(grid * 2, snap_grid(raw_n.dur, grid))
            anchored_bass.append(NoteEvent(best_p, t, dur, velocity=55, is_melody=False))
            last_bass_time = t

    return anchored_bass


# ==============================================================================
# 第五步：多格式导出 (Clean MIDI、15 键按键谱与标准简谱)
# ==============================================================================

def safe_save_file(output_path, write_fn):
    """安全保存文件：防止 Windows 媒体播放器独占文件时 PermissionError 闪退崩溃"""
    try:
        write_fn(output_path)
        return output_path
    except PermissionError:
        base, ext = os.path.splitext(output_path)
        fallback_path = f"{base}_new{ext}"
        try:
            write_fn(fallback_path)
            print(f"[*] 提示: 原文件 '{output_path}' 正被播放器占用，已安全保存至: '{fallback_path}'")
            return fallback_path
        except Exception:
            raise


def export_clean_midi(melody_notes, bass_notes, tpb, bpm, grid, output_path):
    """导出标准光遇 Clean MIDI 文件（主旋律清晰响亮，伴奏轻柔衬托）"""
    mid = mido.MidiFile(ticks_per_beat=tpb)

    meta_track = mido.MidiTrack()
    mid.tracks.append(meta_track)
    meta_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    meta_track.append(mido.MetaMessage("track_name", name="Sky Music Master", time=0))
    meta_track.append(mido.MetaMessage("end_of_track", time=1))

    bar_ticks = tpb * 4

    def build_melody_track(notes):
        trk = mido.MidiTrack()
        trk.append(mido.MetaMessage("track_name", name="Melody", time=0))
        trk.append(mido.Message("program_change", program=0, time=0))

        if not notes:
            trk.append(mido.MetaMessage("end_of_track", time=tpb))
            return trk

        events = []
        repeat_gap = max(16, grid // 4)

        for i, n in enumerate(notes):
            start = snap_grid(n.start, grid)
            dur = max(grid, snap_grid(n.dur, grid))

            if i + 1 < len(notes):
                next_start = snap_grid(notes[i + 1].start, grid)
                if next_start > start:
                    if notes[i + 1].pitch == n.pitch:
                        dur = min(dur, max(grid // 2, next_start - start - repeat_gap))
                    else:
                        dur = min(dur, next_start - start)

            # 主旋律响亮有歌唱力 (102)
            vel = 102
            pos_in_bar = start % bar_ticks
            if pos_in_bar < grid:
                vel += 5  # 小节强拍加重
            if dur >= tpb:
                vel += 3  # 长音气息加重

            vel = min(120, max(60, vel))

            events.append((start, "on", n.pitch, vel))
            events.append((start + dur, "off", n.pitch, 0))

        events.sort(key=lambda e: (e[0], 0 if e[1] == "off" else 1))

        last_time = 0
        for ev_time, ev_type, pitch, vel in events:
            delta = max(0, ev_time - last_time)
            msg_type = "note_on" if ev_type == "on" else "note_off"
            trk.append(mido.Message(msg_type, note=pitch, velocity=vel, time=delta))
            last_time = ev_time

        trk.append(mido.MetaMessage("end_of_track", time=tpb))
        return trk

    def build_bass_track(notes):
        trk = mido.MidiTrack()
        trk.append(mido.MetaMessage("track_name", name="Accompaniment", time=0))
        trk.append(mido.Message("program_change", program=0, time=0))

        if not notes:
            trk.append(mido.MetaMessage("end_of_track", time=tpb))
            return trk

        events = []
        for n in notes:
            start = snap_grid(n.start, grid)
            dur = max(grid * 2, snap_grid(n.dur, grid))
            events.append((start, "on", n.pitch, 54))  # 伴奏轻柔衬托
            events.append((start + dur, "off", n.pitch, 0))

        events.sort(key=lambda e: (e[0], 0 if e[1] == "off" else 1))

        last_time = 0
        for ev_time, ev_type, pitch, vel in events:
            delta = max(0, ev_time - last_time)
            msg_type = "note_on" if ev_type == "on" else "note_off"
            trk.append(mido.Message(msg_type, note=pitch, velocity=vel, time=delta))
            last_time = ev_time

        trk.append(mido.MetaMessage("end_of_track", time=tpb))
        return trk

    if melody_notes:
        mid.tracks.append(build_melody_track(melody_notes))
    if bass_notes:
        mid.tracks.append(build_bass_track(bass_notes))

    return safe_save_file(output_path, lambda path: mid.save(path))


def export_sky_sheet(all_events, sky_keys, tpb, grid, output_path, title, key_str, shift_str):
    """导出标准光遇 15 键按键谱（A1~C5 坐标排布）"""
    pitch_to_tag = {p: SKY_KEY_TAGS[i] for i, p in enumerate(sky_keys)}

    if not all_events:
        return output_path

    max_end = max(snap_grid(n.start, grid) + max(grid, snap_grid(n.dur, grid)) for n in all_events)
    slots = int(math.ceil(max_end / grid)) + 1
    timeline = [[] for _ in range(slots)]

    for n in all_events:
        slot = int(round(snap_grid(n.start, grid) / grid))
        if 0 <= slot < slots:
            timeline[slot].append(n.pitch)

    def write_body(target_path):
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("============================================================\n")
            f.write("          光遇 15 键按键简谱 (Sky Music 15-Key Sheet)\n")
            f.write("============================================================\n")
            f.write(f"歌曲: {title}\n")
            f.write(f"原调: {key_str}\n")
            f.write(f"移调: {shift_str}\n")
            f.write(f"网格: {grid} ticks / step\n\n")
            f.write("琴键布局:\n")
            f.write("  第一排 (低音): A1  A2  A3  A4  A5\n")
            f.write("  第二排 (中音): B1  B2  B3  B4  B5\n")
            f.write("  第三排 (高音): C1  C2  C3  C4  C5\n")
            f.write("符号说明: '.' = 空拍/延音等待；[] = 和弦同时按压\n")
            f.write("============================================================\n\n")

            tokens = []
            for pit_list in timeline:
                if not pit_list:
                    tokens.append(".")
                else:
                    unique_p = sorted(set(pit_list))
                    tags = [pitch_to_tag[p] for p in unique_p if p in pitch_to_tag]
                    if not tags:
                        tokens.append(".")
                    elif len(tags) == 1:
                        tokens.append(tags[0])
                    else:
                        tokens.append(f"[{''.join(tags)}]")

            slots_per_bar = max(4, int(round(tpb * 4 / grid)))
            for i in range(0, len(tokens), slots_per_bar):
                bar_num = i // slots_per_bar + 1
                f.write(f"第 {bar_num:02d} 小节: " + " ".join(tokens[i:i + slots_per_bar]) + "\n")

    return safe_save_file(output_path, write_body)


def export_simple_notation(all_events, sky_keys, tpb, grid, output_path, title, key_str, mode, base_octave="C4"):
    """导出标准数字简谱 (1 2 3 4 5 6 7，对应标准歌词音高)"""
    deg_map = DEGREE_MAP_C4 if base_octave.upper() == "C4" else DEGREE_MAP_C3

    if not all_events:
        return output_path

    max_end = max(snap_grid(n.start, grid) + max(grid, snap_grid(n.dur, grid)) for n in all_events)
    slots = int(math.ceil(max_end / grid)) + 1
    timeline = [[] for _ in range(slots)]

    for n in all_events:
        slot = int(round(snap_grid(n.start, grid) / grid))
        if 0 <= slot < slots:
            timeline[slot].append(n.pitch)

    def write_body(target_path):
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("============================================================\n")
            f.write("           光遇标准数字简谱 (Numbered Musical Notation)\n")
            f.write("============================================================\n")
            f.write(f"歌曲: {title}\n")
            f.write(f"调性: {key_str}\n")
            f.write("说明: '.' = 延音/空拍；() = 双音同时弹奏\n")
            f.write("      1~7 为中音组，1'~7' 为高音组，1'' 为倍高音组\n")
            f.write("============================================================\n\n")

            tokens = []
            for pit_list in timeline:
                if not pit_list:
                    tokens.append(".")
                else:
                    unique_p = sorted(set(pit_list))
                    degs = [deg_map.get(p, "?") for p in unique_p if p in deg_map]
                    if not degs:
                        tokens.append(".")
                    elif len(degs) == 1:
                        tokens.append(degs[0])
                    else:
                        tokens.append(f"({'/'.join(degs)})")

            slots_per_bar = max(4, int(round(tpb * 4 / grid)))
            for i in range(0, len(tokens), slots_per_bar):
                bar_num = i // slots_per_bar + 1
                f.write(f"[{bar_num:02d}] " + " ".join(tokens[i:i + slots_per_bar]) + "\n")

    return safe_save_file(output_path, write_body)


# ==============================================================================
# 核心主调度流水线 (Pipeline Coordinator)
# ==============================================================================

def process_midi_to_sky(
    input_midi_path,
    output_midi_path=None,
    output_sheet_path=None,
    output_simple_path=None,
    base_octave="auto",
    solo_melody_only=False,
    verbose=True,
):
    """光遇友好型 MIDI 改谱 V7 核心流水线"""
    if verbose:
        print()
        print("=" * 70)
        print("   光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer V7 原曲高保真版)")
        print("=" * 70)
        print(f"[*] 输入文件: {input_midi_path}")

    # 1. 解析 MIDI
    tracks_notes, tpb, bpm = parse_midi_file(input_midi_path)
    total_raw = sum(len(t[2]) for t in tracks_notes)
    if verbose:
        print(f"[*] 解析完成: 音轨数 = {len(tracks_notes)}, 原始音符 = {total_raw}, TPB = {tpb}, BPM = {bpm:.1f}")

    if total_raw == 0:
        raise ValueError("输入 MIDI 文件中未检测到有效音符！")

    # 2. 原曲主旋律歌唱流提取与乐理伪音过滤
    melody_raw, accomp_pool = extract_pure_melody_and_accompaniment(tracks_notes, tpb)
    melody_shaped = shape_legato_melody(melody_raw, tpb)
    if verbose:
        print(f"[*] 声部解耦: 提取原曲主歌唱线条 = {len(melody_shaped)} 音符 (已完成泛音归一化、伪音剔除与歌唱连音塑形)")

    # 3. 自适应音域决策 (智能推荐 C4 黄金演唱音区)
    if base_octave == "auto" or base_octave is None:
        # 评估 C4 (60~84) vs C3 (48~72)
        c4_in = sum(1 for n in melody_shaped if 60 <= n.pitch <= 84)
        c3_in = sum(1 for n in melody_shaped if 48 <= n.pitch <= 72)
        if c4_in >= c3_in or mean([n.pitch for n in melody_shaped]) >= 64:
            selected_base = "C4"
        else:
            selected_base = "C3"
    else:
        selected_base = base_octave.upper()

    if selected_base == "C4":
        sky_keys = SKY_KEYS_C4
        base_label = "C4~C6 (60~84) [光遇黄金演唱音区，原曲高辨识推荐]"
    else:
        sky_keys = SKY_KEYS_C3
        base_label = "C3~C5 (48~72) [低音区]"

    if verbose:
        print(f"[*] 目标音域基准: {base_label}")

    # 4. 调性识别与全曲最佳移调
    key_name, mode_name, tonic_num = detect_key_and_mode(melody_shaped)
    key_full_str = f"{key_name} {mode_name.capitalize()}"

    best_k, best_oct, total_shift, white_rate = find_optimal_sky_transposition(melody_shaped, sky_keys)
    k_str = f"+{best_k}" if best_k >= 0 else f"{best_k}"
    oct_str = f"+{best_oct}" if best_oct >= 0 else f"{best_oct}"
    tot_str = f"+{total_shift}" if total_shift >= 0 else f"{total_shift}"

    if verbose:
        print(f"[*] 调性分析: 识别原曲调性为 {key_full_str}")
        print(f"[*] 全局移调: 调性半音位移 {k_str} (白键率: {white_rate*100:.1f}%), 八度位移 {oct_str} (总位移: {tot_str} 半音)")

    # 5. 音程保真 Viterbi 动态规划
    mapped_melody = map_melody_sequence_dp(melody_shaped, total_shift, sky_keys)

    target_max = max(sky_keys)
    over_high = sum(1 for n in mapped_melody if n.pitch > target_max)

    raw_shifted = [n.pitch + total_shift for n in melody_shaped]
    exact_match = sum(1 for s, d in zip(raw_shifted, mapped_melody) if s == d.pitch)
    correct_dir = 0
    total_dir = 0
    for i in range(1, len(melody_shaped)):
        rd = raw_shifted[i] - raw_shifted[i - 1]
        md = mapped_melody[i].pitch - mapped_melody[i - 1].pitch
        if rd != 0:
            total_dir += 1
            if (rd > 0 and md > 0) or (rd < 0 and md < 0):
                correct_dir += 1

    exact_pct = exact_match / max(1, len(melody_shaped)) * 100
    dir_pct = correct_dir / max(1, total_dir) * 100
    if verbose:
        print(f"[*] 原曲高保真映射: 旋律吻合率 = {exact_pct:.1f}%, 走向保持率 = {dir_pct:.1f}%, 高音折叠缺失 = {over_high} 处")

    # 6. 律动网格对齐与极简强拍低音架构
    grid = choose_rhythm_grid(melody_shaped, tpb)
    if verbose:
        print(f"[*] 律动网格: 选择 {grid} ticks/step 音乐脉冲网格")

    if solo_melody_only:
        mapped_bass = []
        if verbose:
            print("[*] 独奏模式: 已忽略伴奏声部，仅保留纯主旋律 (辨识度最高)")
    else:
        mapped_bass = build_sparse_strong_beat_bass(accomp_pool, total_shift, mapped_melody, sky_keys, tpb, grid)
        if verbose:
            print(f"[*] 极简低音: 提取小节强拍纯净根音 = {len(mapped_bass)} 音符 (主次分明，绝不喧宾夺主)")

    # 7. 导出文件
    base_name = os.path.splitext(input_midi_path)[0]
    out_mid = output_midi_path or f"{base_name}_sky.mid"
    out_sheet = output_sheet_path or f"{base_name}_sky_sheet.txt"
    out_simple = output_simple_path or f"{base_name}_simple.txt"
    title_str = os.path.basename(base_name)

    saved_mid = export_clean_midi(mapped_melody, mapped_bass, tpb, bpm, grid, out_mid)

    all_events = sorted(mapped_melody + mapped_bass, key=lambda n: (snap_grid(n.start, grid), -n.pitch))
    saved_sheet = export_sky_sheet(all_events, sky_keys, tpb, grid, out_sheet, title_str, key_full_str, tot_str)
    saved_simple = export_simple_notation(all_events, sky_keys, tpb, grid, out_simple, title_str, key_full_str, mode_name, selected_base)

    if verbose:
        print("-" * 70)
        print(f"[完成] 光遇 Clean MIDI:   {os.path.abspath(saved_mid)}")
        print(f"[完成] 光遇 15 键文本谱:  {os.path.abspath(saved_sheet)}")
        print(f"[完成] 数字简谱文本:      {os.path.abspath(saved_simple)}")
        print("=" * 70)

    return {
        "midi_path": saved_mid,
        "sheet_path": saved_sheet,
        "simple_path": saved_simple,
        "total_shift": total_shift,
        "melody_count": len(mapped_melody),
        "bass_count": len(mapped_bass),
        "fidelity_exact": exact_pct,
        "fidelity_direction": dir_pct,
    }


# ==============================================================================
# 交互模式与 CLI 主入口
# ==============================================================================

def select_midi_interactively():
    """交互式列出工作区可用 MIDI 文件"""
    candidates = [
        f for f in os.listdir(".")
        if f.lower().endswith((".mid", ".midi")) and not f.endswith("_sky.mid") and not f.startswith("sky_preview") and not f.startswith("test_")
    ]
    if not candidates:
        print("当前目录下未发现可用的 MIDI 文件！")
        return None

    print("\n请选择要进行改谱的 MIDI 文件:")
    for idx, f in enumerate(candidates, start=1):
        print(f"  [{idx}] {f}")

    while True:
        try:
            choice = input(f"\n请输入序号 (1~{len(candidates)}) [默认 1]: ").strip()
            if not choice:
                return candidates[0]
            num = int(choice)
            if 1 <= num <= len(candidates):
                return candidates[num - 1]
        except (ValueError, KeyboardInterrupt, EOFError):
            pass
        print("输入无效，请重新输入。")


def main():
    parser = argparse.ArgumentParser(
        description="光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer V7 原曲高保真版)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", default=None, help="输入 MIDI 文件路径 (.mid)")
    parser.add_argument("-o", "--output", default=None, help="输出光遇 Clean MIDI 路径")
    parser.add_argument("--sheet", default=None, help="输出光遇 15 键按键谱路径 (.txt)")
    parser.add_argument("--simple", default=None, help="输出数字简谱路径 (.txt)")
    parser.add_argument("--base", choices=["auto", "C4", "C3"], default="auto", help="光遇音域基准: auto(智能匹配黄金音区), C4(推荐 60~84), C3(低音 48~72)")
    parser.add_argument("--solo-only", action="store_true", help="仅保留纯主旋律，剔除全部伴奏 (辨识度最高)")

    args = parser.parse_args()

    input_file = args.input
    if not input_file:
        input_file = select_midi_interactively()
        if not input_file:
            print("未指定有效文件，退出程序。")
            return

    try:
        process_midi_to_sky(
            input_midi_path=input_file,
            output_midi_path=args.output,
            output_sheet_path=args.sheet,
            output_simple_path=args.simple,
            base_octave=args.base,
            solo_melody_only=args.solo_only,
            verbose=True,
        )
    except Exception as exc:
        print(f"\n[错误] 处理失败: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()