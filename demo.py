import math
from collections import defaultdict
from statistics import mean, median

import mido


# ============================================================
# MIDI -> 光遇 15 键简谱转换器 V5
#
# 核心目标：
#   不是“尽可能压缩 MIDI”，而是：
#   1. 尽量正确找出主旋律
#   2. 保留原旋律的音程走向
#   3. 黑键处理采用“全局动态规划”，避免逐音符乱吸附
#   4. 尽量保留原始节奏和切分
#   5. 伴奏只做极弱的低音支撑
#
# 光遇15键：
#   C3 D3 E3 F3 G3 A3 B3
#   C4 D4 E4 F4 G4 A4 B4
#   C5
# ============================================================


SKY_KEYS_MIDI = [
    48, 50, 52, 53, 55, 57, 59,
    60, 62, 64, 65, 67, 69, 71,
    72,
]

SKY_KEY_TAGS = [
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
    "C1", "C2", "C3", "C4", "C5",
]

NOTE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B",
]

WHITE_PITCH_CLASSES = {0, 2, 4, 5, 7, 9, 11}

MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]

MAJOR_PROFILE = [
    6.35, 2.23, 3.48, 2.33,
    4.38, 4.09, 2.52, 5.19,
    2.39, 3.66, 2.29, 2.88,
]

MINOR_PROFILE = [
    6.33, 2.68, 3.52, 5.38,
    2.60, 3.53, 2.54, 4.75,
    3.98, 2.69, 3.34, 3.17,
]


# ============================================================
# 通用工具
# ============================================================

def clamp(value, low, high):
    return max(low, min(high, value))


def pearson(a, b):
    if len(a) != len(b) or not a:
        return 0.0

    ma = mean(a)
    mb = mean(b)

    numerator = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a)
    db = sum((y - mb) ** 2 for y in b)

    denominator = math.sqrt(da * db)
    if denominator == 0:
        return 0.0

    return numerator / denominator


def snap_grid(value, grid):
    return int(round(value / grid) * grid)


def pitch_class_distance(a, b):
    d = abs((a % 12) - (b % 12))
    return min(d, 12 - d)


# ============================================================
# 1. MIDI 音符提取
# ============================================================

def extract_tracks(mid):
    tracks = []

    for track_index, track in enumerate(mid.tracks):
        current_tick = 0
        active = {}
        notes = []

        for msg in track:
            current_tick += msg.time

            if msg.type not in ("note_on", "note_off"):
                continue

            channel = getattr(msg, "channel", 0)
            pitch = getattr(msg, "note", None)
            if pitch is None:
                continue

            # GM 鼓组
            if channel == 9:
                continue

            key = (channel, pitch)

            if msg.type == "note_on" and msg.velocity > 0:
                if key in active:
                    old = active.pop(key)
                    if current_tick > old["start"]:
                        notes.append({
                            "pitch": pitch,
                            "start": old["start"],
                            "dur": current_tick - old["start"],
                            "track": track_index,
                            "channel": channel,
                            "velocity": old["velocity"],
                        })

                active[key] = {
                    "start": current_tick,
                    "velocity": msg.velocity,
                }

            else:
                if key not in active:
                    continue

                old = active.pop(key)
                duration = current_tick - old["start"]

                if duration > 0:
                    notes.append({
                        "pitch": pitch,
                        "start": old["start"],
                        "dur": duration,
                        "track": track_index,
                        "channel": channel,
                        "velocity": old["velocity"],
                    })

        # 没有 note_off 的 MIDI
        fallback_dur = max(mid.ticks_per_beat // 4, 1)
        for (channel, pitch), old in active.items():
            duration = max(fallback_dur, current_tick - old["start"])
            notes.append({
                "pitch": pitch,
                "start": old["start"],
                "dur": duration,
                "track": track_index,
                "channel": channel,
                "velocity": old["velocity"],
            })

        if notes:
            notes.sort(key=lambda n: (n["start"], n["pitch"]))
            tracks.append(notes)

    return tracks


# ============================================================
# 2. 旋律轨评分
#
# V4 的问题：
#   过度依赖“音符数量 + 音域”，鼓励了伴奏轨。
#
# V5：
#   加入：
#   - 同时发声比例
#   - 平均相邻音程
#   - 连续单线条程度
#   - 过密和弦惩罚
#   - 音域合理性
# ============================================================

def score_track(notes, ticks_per_beat):
    if not notes:
        return -999999.0

    ordered = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
    starts = [n["start"] for n in ordered]
    pitches = [n["pitch"] for n in ordered]
    durations = [n["dur"] for n in ordered]

    onset_groups = defaultdict(list)
    for note in ordered:
        onset_groups[note["start"]].append(note)

    polyphonic_onsets = sum(1 for group in onset_groups.values() if len(group) > 1)
    onset_count = len(onset_groups)

    polyphony_rate = polyphonic_onsets / max(1, onset_count)

    avg_pitch = mean(pitches)
    pitch_range = max(pitches) - min(pitches)

    # 有效旋律音程统计
    onset_pitch = []
    for start in sorted(onset_groups):
        group = onset_groups[start]
        onset_pitch.append(max(group, key=lambda n: (n["dur"], n["velocity"], n["pitch"])))

    intervals = [
        abs(b["pitch"] - a["pitch"])
        for a, b in zip(onset_pitch, onset_pitch[1:])
    ]

    if intervals:
        avg_interval = mean(intervals)
        small_motion_rate = sum(1 for x in intervals if x <= 7) / len(intervals)
        huge_leap_rate = sum(1 for x in intervals if x >= 12) / len(intervals)
    else:
        avg_interval = 0.0
        small_motion_rate = 1.0
        huge_leap_rate = 0.0

    short_rate = sum(
        1 for d in durations
        if d <= ticks_per_beat // 2
    ) / len(durations)

    density = len(notes) / max(1, len(set(starts)))
    density_score = clamp(len(notes) / 220.0, 0.0, 1.0)

    pitch_center_score = clamp(
        1.0 - abs(avg_pitch - 69.0) / 35.0,
        0.0,
        1.0,
    )

    range_score = clamp(pitch_range / 30.0, 0.0, 1.0)

    # 太多很大跳跃通常不是单音旋律
    contour_score = (
        small_motion_rate * 28.0
        - huge_leap_rate * 20.0
        + clamp(avg_interval / 8.0, 0.0, 1.0) * 8.0
    )

    score = (
        density_score * 18.0
        + pitch_center_score * 10.0
        + range_score * 18.0
        + (1.0 - polyphony_rate) * 42.0
        + short_rate * 6.0
        + contour_score
        - max(0.0, density - 3.0) * 4.0
    )

    return score


def select_melody(tracks, ticks_per_beat):
    if not tracks:
        return [], []

    if len(tracks) == 1:
        return tracks[0], []

    scored = []
    for index, notes in enumerate(tracks):
        scored.append((
            score_track(notes, ticks_per_beat),
            index,
            notes,
        ))

    scored.sort(key=lambda x: x[0], reverse=True)

    _, melody_index, melody = scored[0]

    accompaniment = []
    for _, index, notes in scored:
        if index != melody_index:
            accompaniment.extend(notes)

    return melody, accompaniment


# ============================================================
# 3. 主旋律清洗：V5 采用“和弦组 + 路径连续性”
#
# V4：
#   同一 onset 永远拿最高音。
#
# 问题：
#   很多 MIDI 的旋律音恰好不是最高音；
#   尤其钢琴/弦乐编配里，高音可能只是和弦内声部。
#
# V5：
#   每个 onset 保留少量候选音，
#   用动态规划选择整条最连续的旋律线。
# ============================================================

def _build_onset_groups(notes, ticks_per_beat):
    min_duration = max(1, ticks_per_beat // 48)

    groups = defaultdict(list)
    for note in notes:
        if note["dur"] >= min_duration:
            groups[note["start"]].append(note)

    result = []
    for start in sorted(groups):
        group = groups[start]
        group.sort(
            key=lambda n: (n["pitch"], n["dur"], n["velocity"]),
            reverse=True,
        )

        # 同音高只留一个
        dedup = []
        seen_pitch = set()
        for note in group:
            if note["pitch"] in seen_pitch:
                continue
            seen_pitch.add(note["pitch"])
            dedup.append(note)

        # 和弦候选最多保留 5 个，防止 DP 爆炸
        result.append((start, dedup[:5]))

    return result


def clean_melody(notes, ticks_per_beat):
    if not notes:
        return []

    groups = _build_onset_groups(notes, ticks_per_beat)
    if not groups:
        return []

    # 每个 onset 各候选一个旋律音
    # DP 状态：
    #   cost
    #   prev_candidate_index
    dp = []
    back = []

    for gi, (_, candidates) in enumerate(groups):
        if gi == 0:
            row = []
            row_back = []
            for ci, note in enumerate(candidates):
                # 中高音略偏好，但不能压过后续连续性
                cost = (
                    -note["dur"] * 0.025
                    -note["velocity"] * 0.008
                    +abs(note["pitch"] - 70) * 0.12
                )
                row.append(cost)
                row_back.append(-1)
            dp.append(row)
            back.append(row_back)
            continue

        prev_candidates = groups[gi - 1][1]
        row = [float("inf")] * len(candidates)
        row_back = [-1] * len(candidates)

        for ci, note in enumerate(candidates):
            best_cost = float("inf")
            best_prev = -1

            for pi, prev_note in enumerate(prev_candidates):
                prev_cost = dp[gi - 1][pi]
                interval = note["pitch"] - prev_note["pitch"]
                abs_interval = abs(interval)

                transition = 0.0

                # 连续旋律奖励
                if abs_interval <= 7:
                    transition -= 2.8
                if abs_interval == 0:
                    transition -= 1.8

                # 大跳不是不允许，但需要明显惩罚
                if abs_interval >= 12:
                    transition += 6.0
                if abs_interval >= 19:
                    transition += 10.0

                # 避免旋律不断向一个方向“漂”
                if gi >= 2:
                    prev_prev_candidates = groups[gi - 2][1]
                    # 这里只做一个非常轻的方向稳定约束
                    if pi < len(back[gi - 1]):
                        ppi = back[gi - 1][pi]
                        if ppi >= 0 and ppi < len(prev_prev_candidates):
                            old_interval = (
                                prev_note["pitch"]
                                - prev_prev_candidates[ppi]["pitch"]
                            )
                            if old_interval * interval < 0 and abs(old_interval) >= 5 and abs(interval) >= 5:
                                transition += 1.5

                # 长音更可能是真正旋律音
                transition -= min(note["dur"], 4 * ticks_per_beat) * 0.002

                candidate_cost = prev_cost + transition
                if candidate_cost < best_cost:
                    best_cost = candidate_cost
                    best_prev = pi

            row[ci] = best_cost
            row_back[ci] = best_prev

        dp.append(row)
        back.append(row_back)

    # 回溯
    last_index = min(range(len(dp[-1])), key=lambda i: dp[-1][i])
    chosen = [None] * len(groups)

    for gi in range(len(groups) - 1, -1, -1):
        chosen[gi] = groups[gi][1][last_index]
        last_index = back[gi][last_index]

    # 清理几乎重叠的极短噪音
    cleaned = []
    for note in chosen:
        if cleaned:
            prev = cleaned[-1]

            if (
                note["pitch"] == prev["pitch"]
                and note["start"] - prev["start"] <= max(1, ticks_per_beat // 32)
            ):
                continue

        cleaned.append(note)

    return cleaned


# ============================================================
# 4. 调性检测
#
# V5：
#   同时考虑：
#   - 音高重量
#   - 长音
#   - 高音
#   - 终止音/句尾音
# ============================================================

def detect_key(melody, all_notes):
    source = melody if len(melody) >= 8 else all_notes

    weights = [0.0] * 12

    if not source:
        return 0, "major", "C 大调"

    last_start = max(n["start"] for n in source)

    for note in source:
        pc = note["pitch"] % 12

        duration_weight = min(note["dur"], 4 * 480) / 480.0
        pitch_weight = clamp((note["pitch"] - 48) / 48.0, 0.0, 1.0)

        # 句尾音稍加强
        tail_weight = 1.0
        if note["start"] >= last_start - 2 * 480:
            tail_weight = 1.28

        weight = (
            duration_weight
            * (1.0 + pitch_weight * 0.12)
            * tail_weight
        )

        weights[pc] += weight

    best_score = -999999.0
    best_tonic = 0
    best_mode = "major"

    for tonic in range(12):
        rotated = [weights[(tonic + i) % 12] for i in range(12)]

        major_score = pearson(rotated, MAJOR_PROFILE)
        minor_score = pearson(rotated, MINOR_PROFILE)

        # 主音实际出现和句尾奖励
        tonic_weight = weights[tonic]
        tonic_score = tonic_weight / max(0.001, sum(weights))

        if major_score + tonic_score * 0.18 > best_score:
            best_score = major_score + tonic_score * 0.18
            best_tonic = tonic
            best_mode = "major"

        if minor_score + tonic_score * 0.18 > best_score:
            best_score = minor_score + tonic_score * 0.18
            best_tonic = tonic
            best_mode = "minor"

    mode_name = "大调" if best_mode == "major" else "小调"
    return best_tonic, best_mode, f"{NOTE_NAMES[best_tonic]} {mode_name}"


# ============================================================
# 5. 整曲转到适合15键的白键空间
#
# V4：
#   只在理论转调附近 +-3 搜索。
#
# V5：
#   直接搜索 12 个半音；
#   评价：
#   - 白键占比
#   - 长音的白键命中
#   - 旋律音程保持
#   - 调性主音落在 C / A 附近
# ============================================================

def choose_normalization_shift(notes, tonic, mode):
    if not notes:
        return 0

    target_tonic = 0 if mode == "major" else 9
    theoretical_shift = target_tonic - tonic

    best_shift = theoretical_shift
    best_score = -999999.0

    for shift in range(-12, 13):
        score = 0.0
        white_weight = 0.0
        total_weight = 0.0

        for note in notes:
            weight = (
                1.0
                + min(note["dur"] / 480.0, 3.0)
                + note["velocity"] / 255.0 * 0.25
            )

            p = note["pitch"] + shift
            pc = p % 12

            total_weight += weight

            if pc in WHITE_PITCH_CLASSES:
                white_weight += weight
                score += 10.0 * weight
            else:
                distance = min(
                    (pc - white) % 12
                    for white in WHITE_PITCH_CLASSES
                )
                distance = min(distance, 12 - distance)
                score -= 9.0 * distance * weight

        white_ratio = white_weight / max(1e-6, total_weight)

        # 理论调性仍然非常重要，避免为了几个 accidentals 把调子搞歪
        distance_from_theory = abs(shift - theoretical_shift)
        theory_penalty = min(distance_from_theory, 12) * 4.5

        # 目标主音偏离 C/A 越大越不利
        shifted_tonic = (tonic + shift) % 12
        target_penalty = pitch_class_distance(shifted_tonic, target_tonic) * 5.0

        score += white_ratio * 80.0
        score -= theory_penalty
        score -= target_penalty

        if score > best_score:
            best_score = score
            best_shift = shift

    return best_shift


# ============================================================
# 6. 全局旋律映射
#
# 这是 V5 最重要的升级。
#
# 不再：
#   每个黑键 -> 最近白键
#
# 而是：
#   每个音生成多个可行白键候选
#   -> 动态规划选择整段最合理路径
#
# 优化目标：
#   A. 尽量少改原音高
#   B. 保留原始音程
#   C. 尽量保留上行/下行方向
#   D. 避免突然跳八度
#   E. 避免 15 键边缘
# ============================================================

def _sky_candidates(raw_pitch):
    candidates = set()

    for octave in range(-2, 3):
        base = raw_pitch + octave * 12

        for sky_pitch in SKY_KEYS_MIDI:
            distance = abs(sky_pitch - base)

            if distance <= 3:
                candidates.add(sky_pitch)

    # 极端音域没有候选时，取最接近的几个键
    if not candidates:
        nearest = sorted(
            SKY_KEYS_MIDI,
            key=lambda p: abs(p - raw_pitch),
        )
        candidates.update(nearest[:3])

    return sorted(candidates)


def _mapping_local_cost(raw_pitch, mapped_pitch):
    diff = abs(mapped_pitch - raw_pitch)

    # 距离 1 的黑键修正很常见，距离 2 已经明显不自然
    if diff == 0:
        return 0.0
    if diff == 1:
        return 1.8
    if diff == 2:
        return 7.0
    return 15.0 + diff * 2.5


def _mapping_transition_cost(raw_a, mapped_a, raw_b, mapped_b):
    raw_interval = raw_b - raw_a
    mapped_interval = mapped_b - mapped_a

    cost = 0.0

    # 重点：保留音程，而不是仅仅保留绝对音高
    interval_error = abs(mapped_interval - raw_interval)
    cost += interval_error * 3.2

    # 上下行方向错了是非常明显的“听感跑调”
    if raw_interval > 0 and mapped_interval < 0:
        cost += 14.0
    elif raw_interval < 0 and mapped_interval > 0:
        cost += 14.0

    # 原本同音，最好仍然同音
    if raw_interval == 0 and mapped_interval != 0:
        cost += 9.0

    # 大跳尽量减少
    if abs(mapped_interval) >= 12:
        cost += 8.0
    if abs(mapped_interval) >= 17:
        cost += 10.0

    return cost


def map_melody_sequence(notes, normalization_shift, octave_shift):
    if not notes:
        return []

    raw_pitches = [
        n["pitch"] + normalization_shift + octave_shift * 12
        for n in notes
    ]

    candidates = [
        _sky_candidates(raw_pitch)
        for raw_pitch in raw_pitches
    ]

    # DP
    dp = []
    back = []

    for i, cand_list in enumerate(candidates):
        row = [float("inf")] * len(cand_list)
        row_back = [-1] * len(cand_list)

        for ci, mapped_pitch in enumerate(cand_list):
            local_cost = _mapping_local_cost(
                raw_pitches[i],
                mapped_pitch,
            )

            # 远离边缘略有奖励，避免 C3/C5 频繁撞边
            edge_penalty = 0.0
            if mapped_pitch in (48, 72):
                edge_penalty = 1.2

            local_cost += edge_penalty

            if i == 0:
                row[ci] = local_cost
                continue

            for pi, prev_mapped_pitch in enumerate(candidates[i - 1]):
                transition = _mapping_transition_cost(
                    raw_pitches[i - 1],
                    prev_mapped_pitch,
                    raw_pitches[i],
                    mapped_pitch,
                )

                total = dp[i - 1][pi] + local_cost + transition

                if total < row[ci]:
                    row[ci] = total
                    row_back[ci] = pi

        dp.append(row)
        back.append(row_back)

    best_index = min(range(len(dp[-1])), key=lambda i: dp[-1][i])

    mapped = [0] * len(notes)

    for i in range(len(notes) - 1, -1, -1):
        mapped[i] = candidates[i][best_index]
        best_index = back[i][best_index]

    result = []
    for note, pitch in zip(notes, mapped):
        result.append({
            **note,
            "mapped_pitch": pitch,
        })

    return result


# ============================================================
# 7. 自动寻找最佳八度
#
# V4：
#   只看覆盖率。
#
# V5：
#   模拟一次完整 DP 映射；
#   用“整体误差 + 边缘惩罚 + 音程保真”选择八度。
# ============================================================

def choose_best_octave_shift(notes, normalization_shift):
    if not notes:
        return 0

    best_shift = 0
    best_score = float("inf")

    for octave_shift in range(-4, 5):
        raw = [
            n["pitch"] + normalization_shift + octave_shift * 12
            for n in notes
        ]

        out_penalty = 0.0
        edge_penalty = 0.0

        for p in raw:
            if p < 48:
                out_penalty += (48 - p) * 8.0
            elif p > 72:
                out_penalty += (p - 72) * 8.0

            if 48 <= p <= 72 and (p <= 50 or p >= 70):
                edge_penalty += 0.8

        mapped = map_melody_sequence(
            notes,
            normalization_shift,
            octave_shift,
        )

        mapping_error = 0.0
        for src, dst in zip(raw, mapped):
            mapping_error += abs(src - dst["mapped_pitch"])

        # 优先：
        #   1. 可映射性
        #   2. 小改动
        #   3. 不顶边
        score = (
            out_penalty * 1.0
            + mapping_error * 5.0
            + edge_penalty
        )

        if score < best_score:
            best_score = score
            best_shift = octave_shift

    return best_shift


# ============================================================
# 8. 节奏网格
#
# 支持：
#   1/8
#   1/16
#   1/32
#
# 目标不是一律 1/16，而是：
#   尽量小的量化误差，同时避免过度碎化。
# ============================================================

def choose_rhythm_grid(notes, ticks_per_beat):
    if len(notes) < 4:
        return max(1, ticks_per_beat // 4)

    starts = sorted(
        set(
            n["start"]
            for n in notes
        )
    )

    if len(starts) < 3:
        return max(1, ticks_per_beat // 4)

    iois = [
        b - a
        for a, b in zip(starts, starts[1:])
        if b > a
    ]

    if not iois:
        return max(1, ticks_per_beat // 4)

    candidates = [
        max(1, ticks_per_beat // 2),  # 1/8
        max(1, ticks_per_beat // 4),  # 1/16
        max(1, ticks_per_beat // 8),  # 1/32
    ]

    best_grid = candidates[1]
    best_score = float("inf")

    for grid in candidates:
        errors = [
            abs(value - snap_grid(value, grid))
            for value in starts
        ]

        mean_error = mean(errors)
        tiny_slot_ratio = sum(1 for x in iois if x < grid) / len(iois)

        # 量化误差是第一目标
        # 1/32 的复杂度稍高，所以加轻微正则
        complexity = {
            candidates[0]: 0.0,
            candidates[1]: 1.0,
            candidates[2]: 2.2,
        }[grid]

        score = mean_error + tiny_slot_ratio * grid * 0.8 + complexity

        if score < best_score:
            best_score = score
            best_grid = grid

    return best_grid


# ============================================================
# 9. 生成旋律事件
# ============================================================

def build_melody_events(
    notes,
    normalization_shift,
    octave_shift,
    ticks_per_beat,
):
    if not notes:
        return [], max(1, ticks_per_beat // 4)

    mapped_notes = map_melody_sequence(
        notes,
        normalization_shift,
        octave_shift,
    )

    grid = choose_rhythm_grid(notes, ticks_per_beat)

    result = []

    for note in mapped_notes:
        start = snap_grid(note["start"], grid)

        # 防止量化后大量不同 onset 合并成一个位置
        result.append({
            "key": SKY_KEYS_MIDI.index(note["mapped_pitch"]),
            "pitch": note["mapped_pitch"],
            "original_pitch": note["pitch"],
            "start": start,
            "end": start + max(grid, snap_grid(note["dur"], grid)),
            "dur": max(grid, snap_grid(note["dur"], grid)),
            "velocity": note["velocity"],
            "is_melody": True,
        })

    # 同一网格只能弹一次：
    # 保留 DP 后旋律连续性更高的事件。
    grouped = defaultdict(list)
    for event in result:
        grouped[event["start"]].append(event)

    final = []

    for start in sorted(grouped):
        group = grouped[start]

        if len(group) == 1:
            final.append(group[0])
            continue

        # 选音高更接近前后邻域的那个
        prev_pitch = final[-1]["pitch"] if final else None

        def rank(event):
            continuity = 0.0
            if prev_pitch is not None:
                continuity = abs(event["pitch"] - prev_pitch)
            return (
                continuity,
                -event["dur"],
                -event["velocity"],
            )

        final.append(min(group, key=rank))

    return final, grid


# ============================================================
# 10. 稀疏低音
#
# 不再“每半拍找一个低音”。
#
# 只在强拍附近抽取，避免伴奏盖掉主旋律。
# ============================================================

def build_bass_events(
    accompaniment,
    normalization_shift,
    octave_shift,
    ticks_per_beat,
    melody_events,
    grid,
):
    if not accompaniment:
        return []

    strong_interval = max(grid * 2, ticks_per_beat // 1)
    min_interval = max(grid * 2, ticks_per_beat // 1)

    melody_starts = {e["start"] for e in melody_events}
    grouped = defaultdict(list)

    for note in accompaniment:
        shifted = (
            note["pitch"]
            + normalization_shift
            + octave_shift * 12
        )

        # 只取原始较低区域
        if shifted > 67:
            continue

        # 最近白键
        nearest = min(
            SKY_KEYS_MIDI,
            key=lambda p: abs(p - shifted),
        )
        pitch = nearest

        while pitch < 48:
            pitch += 12
        while pitch > 59:
            pitch -= 12

        if pitch < 48 or pitch > 59:
            continue

        start = snap_grid(note["start"], grid)

        grouped[start].append({
            "pitch": pitch,
            "key": SKY_KEYS_MIDI.index(pitch),
            "original_pitch": note["pitch"],
            "start": start,
            "end": start + max(grid, snap_grid(note["dur"], grid)),
            "dur": max(grid, snap_grid(note["dur"], grid)),
            "velocity": note["velocity"],
            "is_melody": False,
        })

    result = []
    last = -999999

    for start in sorted(grouped):
        if start - last < min_interval:
            continue

        # 太靠近主旋律起点且同键，不需要低音重复
        if start in melody_starts:
            candidates = [
                x for x in grouped[start]
                if x["key"] <= 6
            ]
        else:
            candidates = grouped[start]

        if not candidates:
            continue

        candidates.sort(
            key=lambda e: (
                e["pitch"],
                -e["dur"],
                -e["velocity"],
            )
        )

        event = candidates[0]

        # 低音只保留在明显强拍附近
        beat_pos = start % strong_interval
        if beat_pos != 0 and not result:
            continue
        if beat_pos != 0 and result and start - result[-1]["start"] < strong_interval:
            continue

        result.append(event)
        last = start

    return result


# ============================================================
# 11. 合并
# ============================================================

def merge_events(melody_events, bass_events):
    result = list(melody_events)

    # Bass 不允许覆盖旋律起点
    melody_start = {
        e["start"] for e in melody_events
    }

    for bass in bass_events:
        if bass["start"] in melody_start:
            # 不同音才加入，而且仅作为很弱的支撑
            same_pitch = any(
                e["start"] == bass["start"]
                and e["pitch"] == bass["pitch"]
                for e in melody_events
            )
            if same_pitch:
                continue

        result.append(bass)

    result.sort(
        key=lambda e: (
            e["start"],
            not e["is_melody"],
            e["pitch"],
        )
    )

    return result


# ============================================================
# 12. 15键时间轴
# ============================================================

def build_timeline(events, grid):
    if not events:
        return [], grid

    max_end = max(e["end"] for e in events)
    slots = int(math.ceil(max_end / grid)) + 1

    timeline = [None] * slots

    for event in events:
        slot = int(round(event["start"] / grid))
        if not (0 <= slot < slots):
            continue

        current = timeline[slot]

        if current is None:
            timeline[slot] = event
            continue

        # 旋律优先
        if event["is_melody"] and not current["is_melody"]:
            timeline[slot] = event
        elif (
            event["is_melody"]
            and current["is_melody"]
            and event["original_pitch"] > current["original_pitch"]
        ):
            timeline[slot] = event

    return timeline, grid


# ============================================================
# 13. 简谱
#
# 重要修正：
#   必须根据“实际15键映射后的 pitch”生成，
#   不能继续拿 original_pitch 直接算。
# ============================================================

def degree_from_mapped_pitch(mapped_pitch, output_tonic=0):
    relative = mapped_pitch - output_tonic
    octave = math.floor(relative / 12)
    pc = relative % 12

    scale = MAJOR_SCALE
    names = ["1", "2", "3", "4", "5", "6", "7"]

    distances = [
        min(abs(pc - s), 12 - abs(pc - s))
        for s in scale
    ]

    degree = distances.index(min(distances))
    token = names[degree]

    if octave < 0:
        token = "[" * min(abs(octave), 2) + token + "]" * min(abs(octave), 2)
    elif octave > 0:
        token = "{" + token + "}"

    return token


def write_simple_sheet(
    events,
    grid,
    output_file,
    title,
    output_tonic,
    original_key,
):
    if not events:
        return

    max_end = max(e["end"] for e in events)
    slots = int(math.ceil(max_end / grid)) + 1

    timeline = [None] * slots

    for event in events:
        slot = int(round(event["start"] / grid))
        if not (0 <= slot < slots):
            continue

        current = timeline[slot]
        if current is None:
            timeline[slot] = event
        elif event["is_melody"] and not current["is_melody"]:
            timeline[slot] = event

    tokens = []

    for event in timeline:
        if event is None:
            tokens.append(".")
        else:
            tokens.append(
                degree_from_mapped_pitch(
                    event["pitch"],
                    output_tonic=output_tonic,
                )
            )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("========================================\n")
        f.write("            光遇15键实际简谱 V5\n")
        f.write("========================================\n")
        f.write(f"歌曲: {title}\n")
        f.write(f"原调: {original_key}\n")
        f.write(f"输出主音: {NOTE_NAMES[output_tonic]}\n")
        f.write(f"网格: {grid} ticks\n")
        f.write("说明: . = 空拍；[1] = 低音；{1} = 高音\n")
        f.write("========================================\n\n")

        for i in range(0, len(tokens), 16):
            f.write(" ".join(tokens[i:i + 16]) + "\n")


# ============================================================
# 14. 15键谱输出
# ============================================================

def write_sky_sheet(
    timeline,
    grid,
    output_file,
    title,
    original_key,
    normalization_shift,
    octave_shift,
    bpm,
):
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("========================================\n")
        f.write("        MIDI -> 光遇 15 键简谱 V5\n")
        f.write("========================================\n")
        f.write(f"歌曲: {title}\n")
        f.write(f"原调: {original_key}\n")
        f.write(f"整体转调: {normalization_shift:+d} 半音\n")
        f.write(f"八度调整: {octave_shift:+d} 八度\n")
        f.write(f"BPM: {bpm:.2f}\n")
        f.write(f"网格: {grid} ticks\n\n")

        f.write("15键映射:\n")
        for i, tag in enumerate(SKY_KEY_TAGS):
            f.write(f"{i + 1:02d}={tag}({SKY_KEYS_MIDI[i]})  ")
            if (i + 1) % 5 == 0:
                f.write("\n")

        f.write("\n")
        f.write("说明: '.' = 等待一个网格时间\n")
        f.write("========================================\n\n")

        tokens = []
        for event in timeline:
            if event is None:
                tokens.append(".")
            else:
                tokens.append(SKY_KEY_TAGS[event["key"]])

        for i in range(0, len(tokens), 16):
            f.write(" ".join(tokens[i:i + 16]) + "\n")


# ============================================================
# 15. 试听 MIDI
# ============================================================

def export_preview_midi(events, ticks_per_beat, output_file, bpm):
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)

    track = mido.MidiTrack()
    mid.tracks.append(track)

    # tempo
    track.append(
        mido.MetaMessage(
            "set_tempo",
            tempo=mido.bpm2tempo(bpm),
            time=0,
        )
    )

    midi_events = []

    for event in events:
        velocity = 100 if event["is_melody"] else 45

        midi_events.append((
            event["start"],
            1,
            event["pitch"],
            velocity,
        ))
        midi_events.append((
            event["end"],
            0,
            event["pitch"],
            0,
        ))

    # note_off 优先于同 tick 的 note_on
    midi_events.sort(key=lambda x: (x[0], x[1]))

    last_tick = 0

    for tick, typ, pitch, velocity in midi_events:
        delta = max(0, tick - last_tick)

        if typ == 1:
            msg = mido.Message(
                "note_on",
                note=pitch,
                velocity=velocity,
                time=delta,
            )
        else:
            msg = mido.Message(
                "note_off",
                note=pitch,
                velocity=0,
                time=delta,
            )

        track.append(msg)
        last_tick = tick

    mid.save(output_file)


# ============================================================
# 16. BPM
# ============================================================

def get_bpm(mid):
    try:
        for track in mid.tracks:
            for msg in track:
                if msg.type == "set_tempo":
                    return mido.tempo2bpm(msg.tempo)
    except Exception:
        pass

    return 120.0


# ============================================================
# 17. 主转换器
# ============================================================

def convert_midi_to_sky(
    input_file,
    output_midi="sky_preview_v5.mid",
    output_sky="sky_sheet_v5.txt",
    output_simple="simple_sheet_v5.txt",
):
    print()
    print("=" * 60)
    print("       MIDI -> 光遇 15 键简谱 V5")
    print("=" * 60)

    mid = mido.MidiFile(input_file)

    print(f"文件: {input_file}")
    print(f"TPB: {mid.ticks_per_beat}")

    bpm = get_bpm(mid)
    print(f"BPM: {bpm:.2f}")

    # 1. 提取
    tracks = extract_tracks(mid)
    if not tracks:
        raise RuntimeError("MIDI 中没有有效音符")

    all_notes = [n for track in tracks for n in track]

    print(f"[1/8] 总音符: {len(all_notes)}")
    print(f"      Track: {len(tracks)}")

    # 2. 旋律轨
    melody, accompaniment = select_melody(
        tracks,
        mid.ticks_per_beat,
    )

    print(f"[2/8] 旋律候选: {len(melody)}")
    print(f"      伴奏候选: {len(accompaniment)}")

    # 3. 旋律清洗
    melody = clean_melody(
        melody,
        mid.ticks_per_beat,
    )

    if not melody:
        raise RuntimeError("无法提取主旋律")

    print(f"[3/8] 旋律清洗: {len(melody)}")

    # 4. 调性
    tonic, mode, key_desc = detect_key(
        melody,
        all_notes,
    )

    print(f"[4/8] 原调: {key_desc}")

    # 5. 转调
    normalization_shift = choose_normalization_shift(
        melody,
        tonic,
        mode,
    )

    print(f"[5/8] 整体转调: {normalization_shift:+d} 半音")

    # 6. 八度
    octave_shift = choose_best_octave_shift(
        melody,
        normalization_shift,
    )

    print(f"[6/8] 八度: {octave_shift:+d}")

    # 7. 旋律
    melody_events, grid = build_melody_events(
        melody,
        normalization_shift,
        octave_shift,
        mid.ticks_per_beat,
    )

    print(f"[7/8] 旋律事件: {len(melody_events)}")
    print(f"      网格: {grid} ticks")

    # 8. Bass
    bass_events = build_bass_events(
        accompaniment,
        normalization_shift,
        octave_shift,
        mid.ticks_per_beat,
        melody_events,
        grid,
    )

    print(f"      Bass事件: {len(bass_events)}")

    # 合并
    final_events = merge_events(
        melody_events,
        bass_events,
    )

    print(f"      最终事件: {len(final_events)}")

    timeline, _ = build_timeline(
        final_events,
        grid,
    )

    # 实际输出主音：
    # major -> C
    # minor -> A
    output_tonic = 0 if mode == "major" else 9

    write_sky_sheet(
        timeline,
        grid,
        output_sky,
        input_file,
        key_desc,
        normalization_shift,
        octave_shift,
        bpm,
    )

    write_simple_sheet(
        final_events,
        grid,
        output_simple,
        input_file,
        output_tonic,
        key_desc,
    )

    export_preview_midi(
        final_events,
        mid.ticks_per_beat,
        output_midi,
        bpm,
    )

    print()
    print("=" * 60)
    print("转换完成！")
    print("=" * 60)
    print(f"原曲调性    : {key_desc}")
    print(f"整体转调    : {normalization_shift:+d}")
    print(f"八度调整    : {octave_shift:+d}")
    print(f"网格        : {grid} ticks")
    print(f"最终音符    : {len(final_events)}")
    print(f"试听 MIDI   : {output_midi}")
    print(f"15键谱      : {output_sky}")
    print(f"数字简谱    : {output_simple}")
    print("=" * 60)


if __name__ == "__main__":
    convert_midi_to_sky(
        "鸳鸯戏.mid",
        "sky_preview_v5.mid",
        "sky_sheet_v5.txt",
        "simple_sheet_v5.txt",
    )
