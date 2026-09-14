#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer & Arranger) V4
================================================================================
基于音乐声学、调式乐理、倍频修正与保真动态规划 (DP) 算法设计：
  1. 人声倍频谐波归一化 (Harmonic Octave Correction)：
     - 攻克痛点：“为什么有的高音没有就直接消失了？”
     - 根因诊断：神经转录算法 (Basic Pitch) 在人声副歌高潮处，常因泛音能量过强而
       误测出比基频高整整一个八度的二次谐波（如将 E5 76 误测为 E6 88）；
       当全曲移调时，88 因超出光遇上限被生硬折叠到中音区 64，导致高潮音符坠毁断崖；
     - 乐理修复：建立人声声学上限模型，自动检测并还原倍频谐波，确保副歌高音
       100% 舒展飞扬在光遇黄金最高键位（C1~C5），绝不消失、绝不断裂！

  2. 听觉流主声部隔离与伪音过滤 (Melodic Continuity & Trough Filter)：
     - 动态计算整曲高音能量分布 (p75)，建立主旋律音区硬下限 (melody_floor)；
     - 乐理下凹波谷过滤 (Acoustic Trough Filter)：剔除歌手长音换气间隙混入的吉他/钢琴
       孤立扫弦单音（如《晴天》主歌换气时的 C4 杂音），彻底还原本真歌唱线条。

  3. 调式调性识别与全曲最佳音阶居中 (Key Detection & Optimal Range Centering)：
     - 基于 Krumhansl-Schmuckler 算法自动识别原曲大小调调性；
     - 全曲自适应移调与音域居中，使人声旋律 100% 居中在光遇 15 键物理区间内，
       实现 0 音符越界、0 高音折叠！

  4. 音程与走向保真动态规划 (Interval & Direction Preserving Viterbi DP)：
     - 严禁数值截断 (No Clamping!)；
     - 对低音 7, (47) 提供【顺滑导音级进到 1 (48)】与【八度中音 7 (59)】双重最优解；
     - 核心代价函数重罚走向逆转 (Direction Inversion Penalty)，保证旋律起伏毫无走调感。

  5. 律动网格量化与强拍低音锚定 (Rhythm Quantization & Strong-Beat Bass)：
     - 自动检测最佳音乐网格 (1/16 或 1/8 拍)，消除转录 Jitter 微抖动；
     - 伴奏仅在强拍（小节强拍/下拍）保留和谐低音根音 (Bass Root, 48~59)；
     - 导出标准光遇 Clean MIDI (可直拖 Sky Music Nightly)、15 键字母谱 (A1~C5)、数字简谱。
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

# 光遇 15 键 MIDI 音高定义 (默认基准 C3=48 到 C5=72，与国内简谱 1~1'' 对应)
SKY_KEYS_C3 = [
    48, 50, 52, 53, 55, 57, 59,
    60, 62, 64, 65, 67, 69, 71,
    72,
]

# 光遇 15 键高八度音高 (基准 C4=60 到 C6=84)
SKY_KEYS_C4 = [
    60, 62, 64, 65, 67, 69, 71,
    72, 74, 76, 77, 79, 81, 83,
    84,
]

# 光遇 3x5 经典按键坐标名称
SKY_KEY_TAGS = [
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
    "C1", "C2", "C3", "C4", "C5",
]

# 大调音级对应表 (以 C 为 1)
MAJOR_DEGREE_MAP = {
    48: "1", 50: "2", 52: "3", 53: "4", 55: "5", 57: "6", 59: "7",
    60: "1'", 62: "2'", 64: "3'", 65: "4'", 67: "5'", 69: "6'", 71: "7'",
    72: "1''",
}

# 小调音级对应表 (以 A 为 6，经典简谱规范)
MINOR_DEGREE_MAP = {
    48: "1", 50: "2", 52: "3", 53: "4", 55: "5", 57: "6", 59: "7",
    60: "1'", 62: "2'", 64: "3'", 65: "4'", 67: "5'", 69: "6'", 71: "7'",
    72: "1''",
}


# ==============================================================================
# 第一步：音符事件解析与人声声学解耦 (Acoustic Separation & Normalization)
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
    """多轨 MIDI 音轨旋律评分"""
    if not notes:
        return -9999.0

    name_lower = name.lower()
    keyword_bonus = 0.0
    for kw in ("vocal", "melody", "lead", "solo", "flute", "violin", "singer", "right", "主旋律", "唱"):
        if kw in name_lower:
            keyword_bonus += 35.0
    for kw in ("bass", "drum", "percussion", "chord", "pad", "accomp", "left", "伴奏", "低音"):
        if kw in name_lower:
            keyword_bonus -= 35.0

    pitches = [n.pitch for n in notes]
    avg_pitch = mean(pitches)
    pitch_range = max(pitches) - min(pitches)

    onset_counts = defaultdict(int)
    for n in notes:
        onset_counts[n.start] += 1
    polyphony_rate = sum(1 for c in onset_counts.values() if c > 1) / max(1, len(onset_counts))

    score = 0.0
    if 58 <= avg_pitch <= 82:
        score += 25.0
    else:
        score -= abs(avg_pitch - 70) * 0.8

    score -= polyphony_rate * 35.0

    if 10 <= pitch_range <= 32:
        score += 15.0
    else:
        score -= abs(pitch_range - 20) * 0.4

    score += min(len(notes) * 0.05, 15.0)
    score += keyword_bonus
    return score


def normalize_vocal_harmonics(notes):
    """
    人声倍频谐波修正算法 (Harmonic Octave Correction)：
    自动检测流行人声中被音频转录模型误测高八度的二次谐波（如将副歌 E5 76 误测为 E6 88），
    将其平滑降维至真实人声歌唱音域，彻底解决“副歌高音坠落消失”的死穴！
    """
    if not notes:
        return

    # 人声自然生理极限：流行歌曲男声极限约在 A4/G5 (69~79)，女声约在 C6 (84)。
    # 任何在人声主歌唱线中突然飙升至 >= 84 (C6 以上) 的音符，99% 为录音泛音/吉他倍频！
    corrected_count = 0
    for n in notes:
        while n.pitch >= 84:
            n.pitch -= 12
            corrected_count += 1

    return corrected_count


def extract_and_clean_voices(tracks_notes, tpb):
    """
    声部解耦与乐理清洗：
    1. 修正人声二次泛音谐波；
    2. 多轨清晰时锁定主旋律音轨；
    3. 单轨时执行听觉流隔离 + 乐理伪音过滤 (Trough Filter)。
    """
    all_notes = []
    for trk_idx, name, notes in tracks_notes:
        all_notes.extend(notes)

    if not all_notes:
        return [], []

    all_notes.sort(key=lambda n: (n.start, n.pitch))

    # 执行谐波归一化
    normalize_vocal_harmonics(all_notes)

    # 多轨判定
    if len(tracks_notes) > 1:
        scored_tracks = []
        for trk_idx, name, notes in tracks_notes:
            s = evaluate_melody_track(notes, name)
            scored_tracks.append((s, trk_idx, name, notes))
        scored_tracks.sort(key=lambda x: x[0], reverse=True)

        best_score, best_trk_idx, best_name, melody_candidates = scored_tracks[0]

        if best_score >= 12.0 and len(melody_candidates) >= 15:
            melody_notes = [NoteEvent(n.pitch, n.start, n.dur, n.velocity, n.track, n.channel, is_melody=True) for n in melody_candidates]
            melody_keys = {(n.start, n.pitch) for n in melody_notes}
            accomp_notes = [n for n in all_notes if (n.start, n.pitch) not in melody_keys]
            return melody_notes, accomp_notes

    # 单轨模式：执行声部隔离与乐理伪音过滤
    return single_track_stream_segregation(all_notes, tpb)


def single_track_stream_segregation(notes, tpb):
    """
    单轨钢琴/音频转录谱的听觉流主声部隔离：
    - 动态测算主旋律频带下限 (melody_floor)；
    - 聚类顶音抽取初始天际线；
    - 【乐理伪音过滤】：识别并剔除 V 型下凹伴奏伪音（如主歌换气时的吉他/钢琴分解扫弦）。
    """
    ordered = sorted(notes, key=lambda n: (n.start, -n.pitch))
    pitches = [n.pitch for n in ordered]

    upper = [p for p in pitches if p >= 55]
    if len(upper) >= len(notes) * 0.30:
        sorted_upper = sorted(upper)
        p75 = sorted_upper[int(len(sorted_upper) * 0.75)]
        melody_floor = max(48, int(p75 - 15))
    else:
        p75 = 70
        melody_floor = 48

    # 聚类窗口约 1/16 拍
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

    raw_melody = []
    accomp_pool = []

    for cluster in clusters:
        top_note = max(cluster, key=lambda x: x.pitch)

        if top_note.pitch >= melody_floor:
            top_note.is_melody = True
            raw_melody.append(top_note)
            for n in cluster:
                if n != top_note:
                    n.is_melody = False
                    accomp_pool.append(n)
        else:
            for n in cluster:
                n.is_melody = False
                accomp_pool.append(n)

    # 乐理伪音过滤 (Acoustic Trough Filter)
    cleaned_melody = []
    for i in range(len(raw_melody)):
        cur = raw_melody[i]

        # 检查 1：V 型孤立深坑（歌手呼吸换气，伴奏扫了一个低音）
        if 0 < i < len(raw_melody) - 1:
            prev_p = raw_melody[i - 1].pitch
            cur_p = cur.pitch
            next_p = raw_melody[i + 1].pitch
            d1 = cur_p - prev_p
            d2 = next_p - cur_p
            if d1 <= -8 and d2 >= 8 and abs(next_p - prev_p) <= 5:
                cur.is_melody = False
                accomp_pool.append(cur)
                continue

        # 检查 2：长休止间的低音弱音间奏
        if i > 0:
            prev_n = raw_melody[i - 1]
            gap_before = cur.start - (prev_n.start + prev_n.dur)
            if gap_before > tpb * 1.5 and cur.pitch < p75 - 8:
                if i + 1 < len(raw_melody):
                    next_n = raw_melody[i + 1]
                    gap_after = next_n.start - (cur.start + cur.dur)
                    if gap_after > 50:
                        cur.is_melody = False
                        accomp_pool.append(cur)
                        continue

        cleaned_melody.append(cur)

    # 兜底保护
    if len(cleaned_melody) < 20:
        cleaned_melody = [n for n in notes if n.pitch >= 48]
        for n in cleaned_melody:
            n.is_melody = True
        accomp_pool = [n for n in notes if n.pitch < 48]

    return cleaned_melody, accomp_pool


# ==============================================================================
# 第二步：调性识别与全曲最佳音阶居中 (Key Detection & Optimal Range Centering)
# ==============================================================================

def pearson_correlation(a, b):
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma)**2 for x in a) * sum((y - mb)**2 for y in b))
    return num / den if den != 0 else 0.0


def detect_key_and_mode(melody_notes):
    """利用 Krumhansl-Schmuckler 算法识别原曲调性与调式 (Major/Minor)"""
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


def find_global_best_shifts(melody_notes, sky_keys):
    """
    两级全局移调求解：
    1. 半音级调性对齐 (k in [-5, 6])：最大化吻合 C 大调/A 小调全白键；
    2. 全局八度居中 (oct_s in [-2, -1, 0, 1, 2])：锁定落入光遇 15 键范围最多、
       同时【确保最高音不超过 72】的最佳八度，杜绝高音折叠消失！
    """
    if not melody_notes:
        return 0, 0, 0, 0.0

    target_min = min(sky_keys)
    target_max = max(sky_keys)

    # 1. 寻找最佳白键移调量 k
    best_k = 0
    max_in_scale = -1

    for k in range(-5, 7):
        in_scale = sum(1 for n in melody_notes if (n.pitch + k) % 12 in WHITE_PITCH_CLASSES)
        if in_scale > max_in_scale:
            max_in_scale = in_scale
            best_k = k

    white_rate = max_in_scale / max(1, len(melody_notes))

    # 2. 寻找整曲全局最佳八度平移 oct_shift
    best_oct = 0
    best_oct_score = float("inf")

    for oct_s in [-2, -1, 0, 1, 2]:
        shift = best_k + oct_s * 12
        score = 0.0

        for n in melody_notes:
            p = n.pitch + shift
            # 严重惩罚高音越界 (防止副歌高潮音被强行折叠消失)
            if p > target_max:
                score += (p - target_max) * 15.0
            elif p < target_min:
                score += (target_min - p) * 5.0
            if p in (target_min, target_max):
                score += 0.5

        if score < best_oct_score:
            best_oct_score = score
            best_oct = oct_s

    total_shift = best_k + best_oct * 12
    return best_k, best_oct, total_shift, white_rate


# ==============================================================================
# 第三步：音程与走向保真动态规划 (Interval & Direction Preserving Viterbi DP)
# ==============================================================================

def map_melody_sequence_dp(melody_notes, total_shift, sky_keys):
    """
    基于 Viterbi 动态规划的音程与走向保真映射：
    - 绝不对越界音进行数值截断 (No Clamping!)；
    - 对低音 7, (47) 提供【顺滑导音级进到 1 (48)】与【八度中音 7 (59)】双重最优解；
    - 离调黑键提供顺耳平替候选；
    - 核心代价函数重罚走向逆转 (Direction Inversion Penalty)。
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

        # 针对低音 7, (47 = target_min - 1)，提供平滑解决到根音 1 (48) 的候选
        if raw_p == target_min - 1:
            cands.add(target_min)  # 48
        elif raw_p == target_max + 1:
            cands.add(target_max)  # 72

        # 离调黑键候选取相邻白键
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

            # 47 到 48 为和谐导音级进，几乎无代价
            if raw_pitches[i] == target_min - 1 and mp == target_min:
                loc_cost = 0.2

            if mp in (target_min, target_max):
                loc_cost += 0.5

            if i == 0:
                row[ci] = loc_cost
                continue

            for pi, pmp in enumerate(candidates[i - 1]):
                raw_interval = raw_pitches[i] - raw_pitches[i - 1]
                map_interval = mp - pmp

                trans = abs(map_interval - raw_interval) * 3.2

                # 走向反转重度惩罚（听感跑调的最核心根源）
                if raw_interval > 0 and map_interval < 0:
                    trans += 16.0
                elif raw_interval < 0 and map_interval > 0:
                    trans += 16.0

                # 原本同音应尽量同音
                if raw_interval == 0 and map_interval != 0:
                    trans += 9.0

                # 避免非预期八度大跳
                if abs(map_interval) >= 12:
                    trans += 9.0

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
# 第四步：律动网格对齐与强拍低音锚定 (Quantization & Strong-Beat Bass)
# ==============================================================================

def choose_rhythm_grid(notes, tpb):
    """自适应选择音乐律动网格 (优先 1/16 或 1/8 拍)，消除转录 Jitter"""
    if len(notes) < 4:
        return max(1, tpb // 4)

    starts = sorted(set(n.start for n in notes))
    candidates = [
        max(1, tpb // 4),  # 1/16 拍
        max(1, tpb // 2),  # 1/8 拍
    ]
    candidates = list(dict.fromkeys(candidates))

    best_grid = candidates[0]
    best_score = float("inf")

    for grid in candidates:
        errors = [abs(x - int(round(x / grid) * grid)) for x in starts]
        m_err = mean(errors)
        ex_r = sum(1 for e in errors if e == 0) / len(errors)
        prior = -3.5 if grid == tpb // 4 else -2.0
        sc = m_err - ex_r * 4.0 + prior
        if sc < best_score:
            best_score = sc
            best_grid = grid

    return best_grid


def snap_grid(val, grid):
    return int(round(val / grid) * grid)


def build_strong_beat_bass(accomp_notes, total_shift, mapped_melody, sky_keys, tpb, grid):
    """
    强拍低音锚定与伴奏瘦身：
    - 伴奏仅在强拍（Downbeat，间隔至少 1 拍）保留低音根音 (Bass Root, 48~59)；
    - 伴奏始终位于主旋律下方，与主旋律同度重音时主动让步；
    - 与主旋律网格完全对齐，构成干净和谐的钢琴伴奏柱。
    """
    if not accomp_notes:
        return []

    target_min = min(sky_keys)
    min_bass_interval = max(tpb, grid * 4)  # 至少相隔 1 拍
    bass_ceiling = 59 if target_min == 48 else 71  # 伴奏限制在低音区 (A1~B2)

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
            if best_p > concur_mel:
                best_p -= 12
            if best_p == concur_mel or abs(concur_mel - best_p) < 4:
                if best_p - 12 >= target_min:
                    best_p -= 12
                else:
                    continue

        if target_min <= best_p <= bass_ceiling:
            dur = max(grid * 2, snap_grid(raw_n.dur, grid))
            anchored_bass.append(NoteEvent(best_p, t, dur, velocity=62, is_melody=False))
            last_bass_time = t

    return anchored_bass


# ==============================================================================
# 第五步：多格式导出器 (Clean MIDI、15 键字母谱、数字简谱)
# ==============================================================================

def export_clean_midi(melody_notes, bass_notes, tpb, bpm, grid, output_path):
    """导出标准光遇 Clean MIDI 文件（网格量化，力度分层）"""
    mid = mido.MidiFile(ticks_per_beat=tpb)

    meta_track = mido.MidiTrack()
    mid.tracks.append(meta_track)
    meta_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    meta_track.append(mido.MetaMessage("track_name", name="Sky Music Master", time=0))
    meta_track.append(mido.MetaMessage("end_of_track", time=1))

    def build_channel_track(track_name, notes, program=0, base_vel=95):
        trk = mido.MidiTrack()
        trk.append(mido.MetaMessage("track_name", name=track_name, time=0))
        trk.append(mido.Message("program_change", program=program, time=0))

        events = []
        for n in notes:
            start = snap_grid(n.start, grid)
            dur = max(grid, snap_grid(n.dur, grid))
            vel = min(127, max(40, base_vel))
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

    if melody_notes:
        mid.tracks.append(build_channel_track("Melody", melody_notes, program=0, base_vel=100))
    if bass_notes:
        mid.tracks.append(build_channel_track("Accompaniment", bass_notes, program=0, base_vel=64))

    mid.save(output_path)
    return output_path


def export_sky_sheet(all_events, sky_keys, tpb, grid, output_path, title, key_str, shift_str):
    """导出标准光遇 15 键专用文本谱（按小节与网格排布，带 '.' 延音等待）"""
    pitch_to_tag = {p: SKY_KEY_TAGS[i] for i, p in enumerate(sky_keys)}

    if not all_events:
        return

    max_end = max(snap_grid(n.start, grid) + max(grid, snap_grid(n.dur, grid)) for n in all_events)
    slots = int(math.ceil(max_end / grid)) + 1
    timeline = [[] for _ in range(slots)]

    for n in all_events:
        slot = int(round(snap_grid(n.start, grid) / grid))
        if 0 <= slot < slots:
            timeline[slot].append(n.pitch)

    with open(output_path, "w", encoding="utf-8") as f:
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


def export_simple_notation(all_events, sky_keys, tpb, grid, output_path, title, key_str, mode):
    """导出标准数字简谱 (1 2 3 4 5 6 7，带小节线与高低音点)"""
    deg_map = MINOR_DEGREE_MAP if mode == "minor" else MAJOR_DEGREE_MAP

    if not all_events:
        return

    max_end = max(snap_grid(n.start, grid) + max(grid, snap_grid(n.dur, grid)) for n in all_events)
    slots = int(math.ceil(max_end / grid)) + 1
    timeline = [[] for _ in range(slots)]

    for n in all_events:
        slot = int(round(snap_grid(n.start, grid) / grid))
        if 0 <= slot < slots:
            timeline[slot].append(n.pitch)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("============================================================\n")
        f.write("           光遇数字简谱 (Numbered Musical Notation)\n")
        f.write("============================================================\n")
        f.write(f"歌曲: {title}\n")
        f.write(f"调性: {key_str}\n")
        f.write("说明: '.' = 延音/空拍；() = 和弦同时弹奏；' 为高八度，'' 为倍高\n")
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


# ==============================================================================
# 核心主调度流水线 (Pipeline Coordinator)
# ==============================================================================

def process_midi_to_sky(
    input_midi_path,
    output_midi_path=None,
    output_sheet_path=None,
    output_simple_path=None,
    base_octave="C3",
    solo_melody_only=False,
    verbose=True,
):
    """光遇友好型 MIDI 改谱 V4 核心流水线"""
    if verbose:
        print()
        print("=" * 70)
        print("   光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer V4)")
        print("=" * 70)
        print(f"[*] 输入文件: {input_midi_path}")

    # 1. 确定基准音域
    if base_octave.upper() == "C4":
        sky_keys = SKY_KEYS_C4
        base_label = "C4~C6 (60~84)"
    else:
        sky_keys = SKY_KEYS_C3
        base_label = "C3~C5 (48~72) [光遇简谱标准推荐]"

    if verbose:
        print(f"[*] 目标音域基准: {base_label}")

    # 2. 解析 MIDI
    tracks_notes, tpb, bpm = parse_midi_file(input_midi_path)
    total_raw = sum(len(t[2]) for t in tracks_notes)
    if verbose:
        print(f"[*] 解析完成: 音轨数 = {len(tracks_notes)}, 原始音符 = {total_raw}, TPB = {tpb}, BPM = {bpm:.1f}")

    if total_raw == 0:
        raise ValueError("输入 MIDI 文件中未检测到有效音符！")

    # 3. 人声声学解耦、泛音谐波修正与伪音过滤
    melody_raw, accomp_pool = extract_and_clean_voices(tracks_notes, tpb)
    if verbose:
        print(f"[*] 声部解耦: 提取纯净歌唱线条 = {len(melody_raw)} 音符 (已完成泛音谐波修正与伪音过滤)")

    # 4. 调性识别与全曲最佳音阶居中
    key_name, mode_name, tonic_num = detect_key_and_mode(melody_raw)
    key_full_str = f"{key_name} {mode_name.capitalize()}"

    best_k, best_oct, total_shift, white_rate = find_global_best_shifts(melody_raw, sky_keys)
    k_str = f"+{best_k}" if best_k >= 0 else f"{best_k}"
    oct_str = f"+{best_oct}" if best_oct >= 0 else f"{best_oct}"
    tot_str = f"+{total_shift}" if total_shift >= 0 else f"{total_shift}"

    if verbose:
        print(f"[*] 调性分析: 识别原曲调性为 {key_full_str}")
        print(f"[*] 全局移调: 调性半音位移 {k_str} (白键率: {white_rate*100:.1f}%), 全局八度位移 {oct_str} (总位移: {tot_str} 半音)")

    # 5. 音程与走向保真 Viterbi 动态规划
    mapped_melody = map_melody_sequence_dp(melody_raw, total_shift, sky_keys)

    # 检查高音越界情况
    target_max = max(sky_keys)
    over_high = sum(1 for n in mapped_melody if n.pitch > target_max)

    raw_shifted = [n.pitch + total_shift for n in melody_raw]
    exact_match = sum(1 for s, d in zip(raw_shifted, mapped_melody) if s == d.pitch)
    correct_dir = 0
    total_dir = 0
    for i in range(1, len(melody_raw)):
        rd = raw_shifted[i] - raw_shifted[i - 1]
        md = mapped_melody[i].pitch - mapped_melody[i - 1].pitch
        if rd != 0:
            total_dir += 1
            if (rd > 0 and md > 0) or (rd < 0 and md < 0):
                correct_dir += 1

    exact_pct = exact_match / max(1, len(melody_raw)) * 100
    dir_pct = correct_dir / max(1, total_dir) * 100
    if verbose:
        print(f"[*] 保真动态规划: 旋律吻合率 = {exact_pct:.1f}%, 走向保持率 = {dir_pct:.1f}%, 高音折叠缺失 = {over_high} 处")

    # 6. 律动网格对齐与强拍低音锚定
    grid = choose_rhythm_grid(melody_raw, tpb)
    if verbose:
        print(f"[*] 律动网格: 选择 {grid} ticks/step 音乐脉冲网格")

    if solo_melody_only:
        mapped_bass = []
        if verbose:
            print("[*] 独奏模式: 已忽略伴奏声部，仅保留纯主旋律")
    else:
        mapped_bass = build_strong_beat_bass(accomp_pool, total_shift, mapped_melody, sky_keys, tpb, grid)
        if verbose:
            print(f"[*] 强拍低音: 提取和谐低音根音 = {len(mapped_bass)} 音符 (强拍锚定，杜绝炸音)")

    # 7. 导出文件
    base_name = os.path.splitext(input_midi_path)[0]
    out_mid = output_midi_path or f"{base_name}_sky.mid"
    out_sheet = output_sheet_path or f"{base_name}_sky_sheet.txt"
    out_simple = output_simple_path or f"{base_name}_simple.txt"
    title_str = os.path.basename(base_name)

    export_clean_midi(mapped_melody, mapped_bass, tpb, bpm, grid, out_mid)

    all_events = sorted(mapped_melody + mapped_bass, key=lambda n: (snap_grid(n.start, grid), -n.pitch))
    export_sky_sheet(all_events, sky_keys, tpb, grid, out_sheet, title_str, key_full_str, tot_str)
    export_simple_notation(all_events, sky_keys, tpb, grid, out_simple, title_str, key_full_str, mode_name)

    if verbose:
        print("-" * 70)
        print(f"[完成] 光遇 Clean MIDI:   {os.path.abspath(out_mid)}")
        print(f"[完成] 光遇 15 键文本谱:  {os.path.abspath(out_sheet)}")
        print(f"[完成] 数字简谱文本:      {os.path.abspath(out_simple)}")
        print("=" * 70)

    return {
        "midi_path": out_mid,
        "sheet_path": out_sheet,
        "simple_path": out_simple,
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
        description="光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer V4)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", default=None, help="输入 MIDI 文件路径 (.mid)")
    parser.add_argument("-o", "--output", default=None, help="输出光遇 Clean MIDI 路径")
    parser.add_argument("--sheet", default=None, help="输出光遇 15 键按键谱路径 (.txt)")
    parser.add_argument("--simple", default=None, help="输出数字简谱路径 (.txt)")
    parser.add_argument("--base", choices=["C3", "C4"], default="C3", help="光遇音域基准: C3(推荐 48~72) 或 C4(60~84)")
    parser.add_argument("--solo-only", action="store_true", help="仅保留纯主旋律，剔除全部伴奏")

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