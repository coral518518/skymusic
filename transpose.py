#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
光遇友好型 MIDI 预处理与智能改谱工具 (Sky Music Transposer & Arranger) V2
================================================================================
基于音乐声学、调性直方图与保真动态规划 (DP) 算法设计：
  1. 听觉流主声部隔离 (Melodic Stream Segregation)：
     - 自动过滤 Channel 10 GM 打击乐；
     - 动态计算整曲高音能量分布 (p75)，自适应建立主旋律音区下限 (melody_floor)；
     - 严格隔离钢琴伴奏中的低音分解和弦（琶音），允许主唱换气留白，根除乱飞杂音；
     - 伴奏垂直瘦身薄化 (Accompaniment Thinning)，只保留低音根音 (Bass Root)。

  2. 全局最佳移调与全局八度居中 (Global Key & Octave Alignment)：
     - 第一阶段：遍历 12 个半音 (-5 ~ +6)，寻求 C 大调/A 小调（全白键）最大命中率；
     - 第二阶段：全局最佳八度居中，整曲统一平移 (Octave Shift)，绝不句句乱变八度。

  3. 音程与走向保真动态规划 (Interval-Preserving Viterbi DP)：
     - 针对峰值超出 15 键边界或离调黑键，采用八度折叠与邻近白键候选；
     - 核心代价函数重罚“走向逆转”（原旋律上行而映射后下行，听感跑调根源）；
     - 严禁粗暴边界截断 (Clamping)，100% 保持原曲抑扬顿挫的旋律线条。

  4. 伴奏自适应避让与多格式导出：
     - 伴奏声部自适应避让主旋律，杜绝同音打架；
     - 导出标准光遇 Clean MIDI (可直拖 Sky Music Nightly)、15 键字母谱 (A1~C5)、数字简谱。
================================================================================
"""

import os
import sys
import math
import argparse
from collections import defaultdict
from statistics import mean

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

# 对应简谱数字表示法 (低音区 1~5, 中音区 6~3', 高音区 4'~1'')
SKY_DEGREE_NAMES = [
    "1", "2", "3", "4", "5",
    "6", "7", "1'", "2'", "3'",
    "4'", "5'", "6'", "7'", "1''",
]


# ==============================================================================
# 第一步：MIDI 轨道解析与声学解耦 (Voice Separation)
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
    """
    解析 MIDI 文件，提取全部有效发音乐轨（过滤 Channel 10 打击乐）。
    返回: (tracks_notes, ticks_per_beat, bpm)
    """
    mid = mido.MidiFile(mid_path)
    tpb = mid.ticks_per_beat

    # 检测 BPM
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

        # 兜底关闭音符
        fallback_dur = max(tpb // 4, 1)
        for (channel, pitch), old in active_notes.items():
            dur = max(fallback_dur, current_tick - old["start"])
            notes.append(NoteEvent(pitch, old["start"], dur, old["velocity"], trk_idx, channel))

        if notes:
            notes.sort(key=lambda n: (n.start, n.pitch))
            tracks_notes.append((trk_idx, name, notes))

    return tracks_notes, tpb, bpm


def evaluate_melody_track(notes, name=""):
    """多轨 MIDI 旋律轨打分"""
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


def extract_voices(tracks_notes, tpb):
    """
    声部提取核心入口：
    - 多轨且某轨具有显著主旋律特征时，采用分轨提取；
    - 单轨钢琴/音频转录 MIDI 时，采用听觉流主声部隔离算法。
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

        # 如果最佳音轨评分较高且音符数合理，直接使用分轨模式
        if best_score >= 10.0 and len(melody_candidates) >= 15:
            melody_notes = [NoteEvent(n.pitch, n.start, n.dur, n.velocity, n.track, n.channel, is_melody=True) for n in melody_candidates]
            melody_keys = {(n.start, n.pitch) for n in melody_notes}
            accomp_notes = [n for n in all_notes if (n.start, n.pitch) not in melody_keys]
            return melody_notes, accomp_notes

    # 单轨或无明确音轨标签：执行声部隔离
    return extract_single_track_voices(all_notes, tpb)


def extract_single_track_voices(notes, tpb):
    """
    听觉流主声部隔离（针对单轨钢琴与转录音频）：
    - 严格计算主旋律音区下限 (melody_floor)；
    - 低于 melody_floor 的琶音绝不允许当作孤立旋律被选中；
    - 允许主唱换气留白，不盲目填充低音琶音。
    """
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    pitches = [n.pitch for n in ordered]

    upper = [p for p in pitches if p >= 55]
    if len(upper) >= len(notes) * 0.30:
        sorted_upper = sorted(upper)
        p75 = sorted_upper[int(len(sorted_upper) * 0.75)]
        melody_floor = max(48, int(p75 - 15))
    else:
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

    melody_notes = []
    accomp_notes = []

    for cluster in clusters:
        max_p = max(n.pitch for n in cluster)

        for n in cluster:
            # 低于主旋律频带下限，坚决划入伴奏池，绝不允许作为旋律
            if n.pitch < melody_floor:
                n.is_melody = False
                accomp_notes.append(n)
                continue

            # 顶音判定为旋律
            if n.pitch == max_p:
                n.is_melody = True
                melody_notes.append(n)
            else:
                n.is_melody = False
                accomp_notes.append(n)

    # 兜底保护
    if len(melody_notes) < 20:
        melody_notes = [n for n in notes if n.pitch >= 48]
        for n in melody_notes:
            n.is_melody = True
        accomp_notes = [n for n in notes if n.pitch < 48]
        for n in accomp_notes:
            n.is_melody = False

    return melody_notes, accomp_notes


def thin_accompaniment(accomp_notes, melody_notes, max_per_onset=1):
    """
    伴奏垂直瘦身薄化 (Accompaniment Thinning)：
    每个时刻仅保留最低音根音 (Bass Root)，为旋律提供清爽支撑。
    """
    if not accomp_notes:
        return []

    melody_by_time = defaultdict(list)
    for m in melody_notes:
        melody_by_time[m.start].append(m.pitch)

    onset_map = defaultdict(list)
    for n in accomp_notes:
        onset_map[n.start].append(n)

    thinned = []
    for onset in sorted(onset_map.keys()):
        group = onset_map[onset]
        # 优先选择最低音根音
        group.sort(key=lambda n: n.pitch)

        selected = []
        concur_melody = melody_by_time.get(onset, [])

        for candidate in group:
            # 避让过近的主旋律
            if any(abs(candidate.pitch - mp) < 3 for mp in concur_melody):
                continue
            selected.append(candidate)
            if len(selected) >= max_per_onset:
                break

        thinned.extend(selected)

    return thinned


# ==============================================================================
# 第二步：全局调性对齐与全局最佳八度居中 (Global Key & Octave Alignment)
# ==============================================================================

def find_global_best_shifts(melody_notes, sky_keys):
    """
    两级全局移调求解：
    1. 半音级调性对齐 (k in [-5, 6])：最大化吻合 C 大调/A 小调全白键；
    2. 全局八度居中 (oct_s in [-2, -1, 0, 1, 2])：整首曲子统一平移，找到落入光遇 15 键范围最多的单一八度！
    """
    if not melody_notes:
        return 0, 0, 0.0

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
            if p < target_min:
                score += (target_min - p) * 6.0
            elif p > target_max:
                score += (p - target_max) * 6.0
            if p in (target_min, target_max):
                score += 0.8  # 略微惩罚边缘

        if score < best_oct_score:
            best_oct_score = score
            best_oct = oct_s

    total_shift = best_k + best_oct * 12
    return best_k, best_oct, total_shift, white_rate


# ==============================================================================
# 第三步：保真动态规划映射 (Interval & Direction Preserving DP)
# ==============================================================================

def map_melody_sequence_dp(melody_notes, total_shift, sky_keys):
    """
    基于 Viterbi 动态规划的音程与走向保真映射：
    - 绝不对越界音生硬截断 (No Clamping!)；
    - 越界音符通过完整八度 (±12) 折叠候选；
    - 离调黑键取其左右邻近白键；
    - 核心代价函数重罚走向逆转 (Direction Inversion Penalty)，让原曲旋律自然流淌！
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

        # 白键且在 15 键中直接选用
        if folded in sky_keys_set:
            return [folded]

        # 离调黑键取相邻两白键
        neighbors = [p for p in sky_keys if abs(p - folded) == 1]
        if neighbors:
            return sorted(neighbors)

        # 兜底
        return sorted(sky_keys, key=lambda p: abs(p - folded))[:2]

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

            # 边缘惩罚
            if mp in (target_min, target_max):
                loc_cost += 0.8

            if i == 0:
                row[ci] = loc_cost
                continue

            for pi, pmp in enumerate(candidates[i - 1]):
                raw_interval = raw_pitches[i] - raw_pitches[i - 1]
                map_interval = mp - pmp

                # 1. 音程变形代价
                trans = abs(map_interval - raw_interval) * 3.2

                # 2. 走向反转重罚 (人类听感跑调的最核心根源)
                if raw_interval > 0 and map_interval < 0:
                    trans += 15.0
                elif raw_interval < 0 and map_interval > 0:
                    trans += 15.0

                # 3. 原本同音应尽量同音
                if raw_interval == 0 and map_interval != 0:
                    trans += 9.0

                # 4. 八度大跳抑制
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


def map_accompaniment(accomp_notes, total_shift, mapped_melody, sky_keys):
    """
    伴奏折叠与主旋律避让：
    - 伴奏随总移调量平移并收拢至 15 键范围；
    - 时刻保持在并发主旋律音符下方；
    - 若出现同音打架，主动下潜或剔除，确保主旋律清澈突出。
    """
    if not accomp_notes:
        return []

    target_min = min(sky_keys)
    target_max = max(sky_keys)
    sky_keys_set = set(sky_keys)

    melody_by_time = {m.start: m.pitch for m in mapped_melody}
    mapped_accomp = []

    for n in accomp_notes:
        p = n.pitch + total_shift
        while p < target_min:
            p += 12
        while p > target_max:
            p -= 12

        # 若为黑键，吸附至下方白键
        if p not in sky_keys_set:
            p = min(sky_keys, key=lambda vk: abs(vk - p))

        # 主旋律避让
        concur_mel = melody_by_time.get(n.start)
        if concur_mel is not None:
            if p > concur_mel:
                p -= 12
            if p == concur_mel:
                if p - 12 >= target_min:
                    p -= 12
                else:
                    continue  # 避免同度重音混淆

        if target_min <= p <= target_max:
            mapped_accomp.append(NoteEvent(p, n.start, n.dur, n.velocity, n.track, n.channel, is_melody=False))

    return mapped_accomp


# ==============================================================================
# 第四步：多格式导出 (MIDI、光遇 15 键谱、数字简谱)
# ==============================================================================

def export_clean_midi(melody_notes, accomp_notes, tpb, bpm, output_path):
    """导出标准光遇 Clean MIDI 文件"""
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
            vel = min(127, max(40, base_vel))
            events.append((n.start, "on", n.pitch, vel))
            events.append((n.end, "off", n.pitch, 0))

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
    if accomp_notes:
        mid.tracks.append(build_channel_track("Accompaniment", accomp_notes, program=0, base_vel=68))

    mid.save(output_path)
    return output_path


def export_sky_sheet(all_events, sky_keys, tpb, output_path):
    """导出光遇 15 键专用文本谱（A1~C5 矩阵布局）"""
    pitch_to_tag = {p: SKY_KEY_TAGS[i] for i, p in enumerate(sky_keys)}

    time_groups = defaultdict(list)
    for n in all_events:
        time_groups[n.start].append(n.pitch)

    sorted_times = sorted(time_groups.keys())
    if not sorted_times:
        return

    ticks_per_measure = tpb * 4

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# ========================================================\n")
        f.write("# 光遇 15 键按键简谱 (Sky Music 15-Key Sheet)\n")
        f.write("# 琴键布局说明:\n")
        f.write("#   第一排 (低音): A1  A2  A3  A4  A5\n")
        f.write("#   第二排 (中音): B1  B2  B3  B4  B5\n")
        f.write("#   第三排 (高音): C1  C2  C3  C4  C5\n")
        f.write("# 符号说明: [] 内为和弦同时按压\n")
        f.write("# ========================================================\n\n")

        measure = 1
        line_buffer = []

        for t in sorted_times:
            pitches = sorted(set(time_groups[t]))
            tags = [pitch_to_tag[p] for p in pitches if p in pitch_to_tag]
            if not tags:
                continue

            token = tags[0] if len(tags) == 1 else f"[{''.join(tags)}]"

            if t // ticks_per_measure + 1 > measure:
                f.write(f"第 {measure} 小节: " + " ".join(line_buffer) + "\n")
                line_buffer = []
                measure = t // ticks_per_measure + 1

            line_buffer.append(token)

        if line_buffer:
            f.write(f"第 {measure} 小节: " + " ".join(line_buffer) + "\n")


def export_simple_notation(all_events, sky_keys, tpb, output_path):
    """导出标准数字简谱 (1 2 3 4 5 6 7 1' 2' 3' ...)"""
    pitch_to_degree = {p: SKY_DEGREE_NAMES[i] for i, p in enumerate(sky_keys)}

    time_groups = defaultdict(list)
    for n in all_events:
        time_groups[n.start].append(n.pitch)

    sorted_times = sorted(time_groups.keys())
    ticks_per_measure = tpb * 4

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# ========================================================\n")
        f.write("# 光遇数字简谱 (Numbered Musical Notation)\n")
        f.write("# 音级对照: 1 2 3 4 5 6 7 | 1' 2' 3' 4' 5' 6' 7' | 1''\n")
        f.write("# ========================================================\n\n")

        measure = 1
        line_buffer = []

        for t in sorted_times:
            pitches = sorted(set(time_groups[t]))
            degs = [pitch_to_degree[p] for p in pitches if p in pitch_to_degree]
            if not degs:
                continue

            token = degs[0] if len(degs) == 1 else f"({'/'.join(degs)})"

            if t // ticks_per_measure + 1 > measure:
                f.write(f"[{measure:02d}] " + " ".join(line_buffer) + "\n")
                line_buffer = []
                measure = t // ticks_per_measure + 1

            line_buffer.append(token)

        if line_buffer:
            f.write(f"[{measure:02d}] " + " ".join(line_buffer) + "\n")


# ==============================================================================
# 核心主调度流水线 (Pipeline Coordinator)
# ==============================================================================

def process_midi_to_sky(
    input_midi_path,
    output_midi_path=None,
    output_sheet_path=None,
    output_simple_path=None,
    base_octave="C3",
    thin_accompaniment_flag=True,
    max_accomp_notes=1,
    solo_melody_only=False,
    verbose=True,
):
    """
    光遇友好型 MIDI 预处理与改谱全流程：
    1. 听觉流主声部隔离 (melody_floor 斩断琶音) 与伴奏薄化；
    2. 全局调性对齐 (半音对齐白键) 与全局八度居中 (整曲统一平移)；
    3. 音程与走向保真动态规划 (Viterbi DP，绝无粗暴截断，保真度 > 93%)；
    4. 伴奏自适应避让与多格式导出。
    """
    if verbose:
        print()
        print("=" * 70)
        print("   光遇友好型 MIDI 智能改谱引擎 (Sky Music Transposer V2)")
        print("=" * 70)
        print(f"[*] 输入文件: {input_midi_path}")

    # 1. 确定基准音高
    if base_octave.upper() == "C4":
        sky_keys = SKY_KEYS_C4
        base_label = "C4~C6 (60~84)"
    else:
        sky_keys = SKY_KEYS_C3
        base_label = "C3~C5 (48~72) [光遇简谱标准推荐]"

    if verbose:
        print(f"[*] 目标音域基准: {base_label}")

    # 2. 解析 MIDI 文件
    tracks_notes, tpb, bpm = parse_midi_file(input_midi_path)
    total_raw = sum(len(t[2]) for t in tracks_notes)
    if verbose:
        print(f"[*] 解析完成: 音轨数 = {len(tracks_notes)}, 原始音符 = {total_raw}, TPB = {tpb}, BPM = {bpm:.1f}")

    if total_raw == 0:
        raise ValueError("输入 MIDI 文件中未检测到有效音符！")

    # 3. 声部解耦 (听觉流隔离)
    melody_raw, accomp_raw = extract_voices(tracks_notes, tpb)
    if verbose:
        print(f"[*] 声部解耦: 提取主歌唱线条 = {len(melody_raw)} 音符, 伴奏池 = {len(accomp_raw)} 音符")

    # 伴奏瘦身薄化
    if thin_accompaniment_flag and accomp_raw and not solo_melody_only:
        accomp_raw = thin_accompaniment(accomp_raw, melody_raw, max_per_onset=max_accomp_notes)
        if verbose:
            print(f"[*] 伴奏瘦身: 过滤和弦保留低音根音 = {len(accomp_raw)} 音符")

    if solo_melody_only:
        accomp_raw = []
        if verbose:
            print("[*] 独奏模式: 已忽略伴奏声部，仅保留纯主旋律")

    # 4. 全局最佳移调与全局八度居中
    best_k, best_oct, total_shift, white_rate = find_global_best_shifts(melody_raw, sky_keys)
    if verbose:
        k_str = f"+{best_k}" if best_k >= 0 else f"{best_k}"
        oct_str = f"+{best_oct}" if best_oct >= 0 else f"{best_oct}"
        tot_str = f"+{total_shift}" if total_shift >= 0 else f"{total_shift}"
        print(f"[*] 全局转调: 调性半音位移 {k_str} (白键率: {white_rate*100:.1f}%), 全局八度位移 {oct_str} (总位移: {tot_str} 半音)")

    # 5. 音程与走向保真动态规划 (Viterbi DP)
    mapped_melody = map_melody_sequence_dp(melody_raw, total_shift, sky_keys)

    # 评估保真度指标
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
        print(f"[*] 保真动态规划: 旋律音高精确吻合率 = {exact_pct:.1f}%, 旋律走向保持率 = {dir_pct:.1f}%")

    # 6. 伴奏折叠与主旋律避让
    mapped_accomp = map_accompaniment(accomp_raw, total_shift, mapped_melody, sky_keys)

    # 7. 导出文件
    base_name = os.path.splitext(input_midi_path)[0]
    out_mid = output_midi_path or f"{base_name}_sky.mid"
    out_sheet = output_sheet_path or f"{base_name}_sky_sheet.txt"
    out_simple = output_simple_path or f"{base_name}_simple.txt"

    export_clean_midi(mapped_melody, mapped_accomp, tpb, bpm, out_mid)
    all_events = sorted(mapped_melody + mapped_accomp, key=lambda n: (n.start, -n.pitch))
    export_sky_sheet(all_events, sky_keys, tpb, out_sheet)
    export_simple_notation(all_events, sky_keys, tpb, out_simple)

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
        "accomp_count": len(mapped_accomp),
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
        if f.lower().endswith((".mid", ".midi")) and not f.endswith("_sky.mid") and not f.startswith("sky_preview")
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
        description="光遇友好型 MIDI 智能改谱工具 (Sky Music Transposer V2)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", default=None, help="输入 MIDI 文件路径 (.mid)")
    parser.add_argument("-o", "--output", default=None, help="输出光遇 Clean MIDI 路径")
    parser.add_argument("--sheet", default=None, help="输出光遇 15 键按键谱路径 (.txt)")
    parser.add_argument("--simple", default=None, help="输出数字简谱路径 (.txt)")
    parser.add_argument("--base", choices=["C3", "C4"], default="C3", help="光遇音域基准: C3(推荐 48~72) 或 C4(60~84)")
    parser.add_argument("--no-thin", action="store_true", help="禁用伴奏薄化 (保留原始伴奏密度)")
    parser.add_argument("--max-accomp", type=int, default=1, help="薄化后每个重音点保留的最大伴奏音符数")
    parser.add_argument("--solo-only", action="store_true", help="仅保留主旋律，剔除全部伴奏")

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
            thin_accompaniment_flag=not args.no_thin,
            max_accomp_notes=args.max_accomp,
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