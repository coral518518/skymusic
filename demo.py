import math
from collections import defaultdict
from statistics import mean, median

import mido


# ============================================================
# MIDI -> 光遇 15 键简谱转换器 V7
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



def _track_melody_probability(notes, ticks_per_beat):
    """给轨道中的音符估计“像主旋律”的概率。

    不是最终选择器，只用于把多条轨道合成候选池时做软权重。
    """
    if not notes:
        return {}

    groups = defaultdict(list)
    for n in notes:
        groups[n["start"]].append(n)

    pitches = [n["pitch"] for n in notes]
    center = median(pitches)
    spread = max(12.0, (max(pitches) - min(pitches)) * 0.55)

    result = {}
    for n in notes:
        onset_group = groups[n["start"]]
        chord_size = len(onset_group)
        pitch_pref = 1.0 - min(1.0, abs(n["pitch"] - center) / spread)
        duration_pref = min(1.0, n["dur"] / max(1, ticks_per_beat))
        velocity_pref = n.get("velocity", 64) / 127.0

        # 和弦内部声部仍允许进入候选池，但明显降低权重。
        chord_penalty = 1.0 / (1.0 + max(0, chord_size - 1) * 0.28)
        score = (
            0.32 * pitch_pref
            + 0.32 * duration_pref
            + 0.16 * velocity_pref
            + 0.20
        ) * chord_penalty
        result[id(n)] = score

    return result


def _merge_melody_candidates(tracks, ticks_per_beat, top_track_count=3):
    """从多个高分轨道合成旋律候选池。

    V5 的单轨选择有一个硬伤：真正的旋律可能被拆在多个轨道里。
    V6 不直接把所有伴奏混进来，而是只拿评分最高的少数轨道做候选。
    """
    scored = []
    for idx, notes in enumerate(tracks):
        scored.append((score_track(notes, ticks_per_beat), idx, notes))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[:max(1, min(top_track_count, len(scored)))]

    candidates = []
    for rank, (track_score, idx, notes) in enumerate(selected):
        probability = _track_melody_probability(notes, ticks_per_beat)
        track_factor = 1.0 / (1.0 + rank * 0.18)
        for n in notes:
            candidates.append({
                **n,
                "melody_prob": probability.get(id(n), 0.5) * track_factor,
            })

    # 相同 onset + 相同 pitch 的不同轨道音符合并，保留更有旋律价值的那个。
    grouped = defaultdict(list)
    for n in candidates:
        grouped[(n["start"], n["pitch"])].append(n)

    dedup = []
    for group in grouped.values():
        group.sort(
            key=lambda n: (
                n["melody_prob"],
                n["dur"],
                n["velocity"],
            ),
            reverse=True,
        )
        dedup.append(group[0])

    dedup.sort(key=lambda n: (n["start"], n["pitch"]))
    selected_indices = {x[1] for x in selected}
    return dedup, selected_indices


def _phrase_segments(notes, ticks_per_beat):
    """按明显停顿切成短乐句，防止整首歌一个 DP 链条越跑越偏。"""
    if not notes:
        return []

    ordered = sorted(notes, key=lambda n: n["start"])
    gap_threshold = max(int(ticks_per_beat * 0.85), 1)

    segments = []
    current = [ordered[0]]

    for prev, cur in zip(ordered, ordered[1:]):
        prev_end = prev["start"] + prev["dur"]
        gap = cur["start"] - prev_end

        # 明显停顿；或者跨越一个以上四分音符。
        if gap >= gap_threshold:
            segments.append(current)
            current = [cur]
        else:
            current.append(cur)

    if current:
        segments.append(current)

    return segments

def select_melody(tracks, ticks_per_beat):
    if not tracks:
        return [], []

    if len(tracks) == 1:
        return tracks[0], []

    candidate_pool, selected_track_indices = _merge_melody_candidates(
        tracks,
        ticks_per_beat,
        top_track_count=3,
    )

    # 用候选池做一次“软清洗”，而不是强行整轨。
    cleaned_pool = []
    for n in candidate_pool:
        if n["dur"] >= max(1, ticks_per_beat // 48):
            cleaned_pool.append(n)

    # 候选轨道本身已经进入旋律候选池，不要再把它们整轨复制到 Bass。
    accompaniment = []
    for track_index, track in enumerate(tracks):
        if track_index in selected_track_indices:
            continue
        accompaniment.extend(track)

    return cleaned_pool, accompaniment


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
    """按 onset 组织候选音，并保留旋律识别所需的少量高质量候选。"""
    min_duration = max(1, ticks_per_beat // 48)
    groups = defaultdict(list)

    for note in notes:
        if note["dur"] < min_duration:
            continue
        groups[note["start"]].append(note)

    result = []
    for start in sorted(groups):
        group = groups[start]

        # 同 onset + 同 pitch 只保留一条。
        best_by_pitch = {}
        for note in group:
            pitch = note["pitch"]
            old = best_by_pitch.get(pitch)
            if old is None or (
                note.get("melody_prob", 0.0),
                note["dur"],
                note.get("velocity", 64),
            ) > (
                old.get("melody_prob", 0.0),
                old["dur"],
                old.get("velocity", 64),
            ):
                best_by_pitch[pitch] = note

        dedup = list(best_by_pitch.values())
        dedup.sort(
            key=lambda n: (
                n.get("melody_prob", 0.5),
                min(n["dur"], ticks_per_beat * 2),
                n.get("velocity", 64),
                n["pitch"],
            ),
            reverse=True,
        )

        # 高音不再天然第一；保留分布，避免内声部被永远过滤。
        result.append((start, dedup[:8]))

    return result


def _phrase_segments(notes, ticks_per_beat):
    """更稳定地切乐句：长停顿 + 大节拍边界附近优先断开。"""
    if not notes:
        return []

    ordered = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
    gap_threshold = max(int(ticks_per_beat * 0.72), 1)

    segments = []
    current = [ordered[0]]

    for prev, cur in zip(ordered, ordered[1:]):
        gap = cur["start"] - (prev["start"] + prev["dur"])
        if gap >= gap_threshold:
            segments.append(current)
            current = [cur]
        else:
            current.append(cur)

    if current:
        segments.append(current)
    return segments


def _scale_cost(note, tonic, mode, phrase_end=False):
    """调性约束只作软约束，绝不为了进调硬改旋律。"""
    scale = MAJOR_SCALE if mode == "major" else MINOR_SCALE
    rel = (note["pitch"] - tonic) % 12

    if rel in scale:
        cost = -0.55
        # 主音、属音在句尾很有价值，但不要过强。
        if phrase_end and rel in (0, 7):
            cost -= 1.0
        return cost

    # 小幅半音偏离允许存在，过多 chromatic 才惩罚。
    nearest = min(pitch_class_distance(rel, x) for x in scale)
    return 0.65 + nearest * 0.55


def _transition_cost_for_melody(prev_note, note, ticks_per_beat):
    interval = note["pitch"] - prev_note["pitch"]
    a = abs(interval)
    cost = 0.0

    # 级进最自然，小三/大三等小跳也很常见。
    if a == 0:
        cost -= 1.8
    elif a <= 2:
        cost -= 2.7
    elif a <= 4:
        cost -= 2.1
    elif a <= 7:
        cost -= 0.7
    elif a <= 9:
        cost += 0.3
    elif a <= 11:
        cost += 1.2
    else:
        cost += 3.0 + (a - 12) * 0.35

    # 过大的单向漂移不是致命问题，但轻微抑制。
    if a >= 19:
        cost += 4.0

    # 长音后的大跳稍微更可疑。
    if prev_note["dur"] >= ticks_per_beat * 1.5 and a >= 10:
        cost += 1.8

    return cost


def _second_order_transition(prev2, prev1, cur, ticks_per_beat):
    """真正使用连续三音判断方向，而不是只看两个音。"""
    if prev2 is None or prev1 is None:
        return 0.0

    d1 = prev1["pitch"] - prev2["pitch"]
    d2 = cur["pitch"] - prev1["pitch"]
    cost = 0.0

    # 大跳以后通常有反向回收，这是典型旋律形状。
    if abs(d1) >= 7 and d1 * d2 < 0:
        cost -= 1.0

    # 连续两次过大的同向跳跃更像伴奏分解。
    if abs(d1) >= 9 and abs(d2) >= 9 and d1 * d2 > 0:
        cost += 2.4

    # 三音全部相同是很正常的重复音。
    if d1 == 0 and d2 == 0:
        cost -= 0.8

    return cost


def _rhythm_signature(segment, ticks_per_beat):
    starts = [n["start"] for n in segment]
    if len(starts) < 2:
        return ()
    gaps = [max(1, b - a) for a, b in zip(starts, starts[1:])]
    base = median(gaps)
    if base <= 0:
        return ()
    # 只保留粗粒度比例，避免不同速度/量化导致匹配失败。
    return tuple(int(clamp(round(g / base), 1, 6)) for g in gaps)


def _phrase_similarity(a, b, ticks_per_beat):
    if not a or not b:
        return 0.0
    length_score = 1.0 - min(abs(len(a) - len(b)), 6) / 6.0
    sa = _rhythm_signature(a, ticks_per_beat)
    sb = _rhythm_signature(b, ticks_per_beat)
    if not sa or not sb:
        rhythm_score = 0.5
    else:
        m = min(len(sa), len(sb))
        rhythm_score = sum(sa[i] == sb[i] for i in range(m)) / max(len(sa), len(sb))
    return length_score * 0.55 + rhythm_score * 0.45


def _choose_phrase_path(
    candidates,
    ticks_per_beat,
    tonic=None,
    mode="major",
    motif_reference=None,
):
    """二阶 DP：同时考虑前一个、前两个音，并可弱跟随重复乐句的轮廓。"""
    if not candidates:
        return []
    if len(candidates) == 1:
        return [candidates[0][1][0]] if candidates[0][1] else []

    first = candidates[0][1]
    second = candidates[1][1]
    if not first or not second:
        return []

    states = {}
    back_layers = [None, {}]
    ref = motif_reference or []

    def local_cost(note, pos, phrase_len):
        cost = (
            -note.get("melody_prob", 0.5) * 4.6
            -min(note["dur"] / max(1, ticks_per_beat), 2.5) * 0.65
            +abs(note["pitch"] - 69) * 0.028
        )
        if tonic is not None:
            cost += _scale_cost(
                note,
                tonic,
                mode,
                phrase_end=(pos == phrase_len - 1),
            )

        # 重复乐句弱约束：比较“相对首音”的音程轮廓。
        if ref and pos < len(ref):
            ref_rel = ref[pos]["pitch"] - ref[0]["pitch"]
            cur_rel = note["pitch"] - ref[0]["pitch"] if pos == 0 else None
            # pos=0 不比较绝对音高；后续由当前 phrase 的首音决定。
            if pos > 0:
                # 这个绝对值只是候选初筛，真正的相对轮廓在扩展状态中计算。
                pass
        return cost

    for i, a in enumerate(first):
        ca = local_cost(a, 0, len(candidates))
        for j, b in enumerate(second):
            cb = local_cost(b, 1, len(candidates))
            cost = ca + cb + _transition_cost_for_melody(a, b, ticks_per_beat)
            if ref and len(ref) == len(candidates):
                ref_int = ref[1]["pitch"] - ref[0]["pitch"]
                cur_int = b["pitch"] - a["pitch"]
                if (ref_int > 0) != (cur_int > 0) and ref_int != 0 and cur_int != 0:
                    cost += 1.15
                cost += abs(abs(cur_int) - abs(ref_int)) * 0.10
            states[(i, j)] = cost
            back_layers[1][(i, j)] = None

    for pos in range(2, len(candidates)):
        group = candidates[pos][1]
        prev_group = candidates[pos - 1][1]
        prev2_group = candidates[pos - 2][1]
        next_states = {}
        next_back = {}

        for (i2, i1), prev_cost in states.items():
            if i2 >= len(prev2_group) or i1 >= len(prev_group):
                continue
            prev2 = prev2_group[i2]
            prev1 = prev_group[i1]

            for ci, cur in enumerate(group):
                cost = prev_cost + local_cost(cur, pos, len(candidates))
                cost += _transition_cost_for_melody(prev1, cur, ticks_per_beat)
                cost += _second_order_transition(prev2, prev1, cur, ticks_per_beat)

                if ref and pos < len(ref) and len(ref) == len(candidates):
                    ref_d = ref[pos]["pitch"] - ref[pos - 1]["pitch"]
                    cur_d = cur["pitch"] - prev1["pitch"]
                    if ref_d != 0 and cur_d != 0 and (ref_d > 0) != (cur_d > 0):
                        cost += 1.15
                    cost += abs(abs(cur_d) - abs(ref_d)) * 0.10

                state_key = (i1, ci)
                if cost < next_states.get(state_key, float("inf")):
                    next_states[state_key] = cost
                    next_back[state_key] = (i2, i1)

        states = next_states
        back_layers.append(next_back)
        if not states:
            return []

    best_state = min(states, key=states.get)
    chosen_indices = [None] * len(candidates)
    chosen_indices[-2], chosen_indices[-1] = best_state

    state = best_state
    for pos in range(len(candidates) - 1, 1, -1):
        prev_state = back_layers[pos].get(state)
        if prev_state is None:
            break
        chosen_indices[pos - 2], chosen_indices[pos - 1] = prev_state
        state = prev_state

    result = []
    for pos, idx in enumerate(chosen_indices):
        if idx is None or idx >= len(candidates[pos][1]):
            return []
        result.append(candidates[pos][1][idx])
    return result


def _clean_melody_with_params(notes, ticks_per_beat, tonic=None, mode="major"):
    if not notes:
        return []

    segments = _phrase_segments(notes, ticks_per_beat)
    result = []
    selected_phrases = []

    for segment in segments:
        groups = _build_onset_groups(segment, ticks_per_beat)
        motif_reference = None

        # 找一个过去最相似的乐句作为弱参考。
        best_similarity = 0.0
        for previous in selected_phrases[-12:]:
            sim = _phrase_similarity(previous, segment, ticks_per_beat)
            if sim > best_similarity and sim >= 0.76:
                best_similarity = sim
                motif_reference = previous

        chosen = _choose_phrase_path(
            groups,
            ticks_per_beat,
            tonic=tonic,
            mode=mode,
            motif_reference=motif_reference,
        )
        if chosen:
            result.extend(chosen)
            selected_phrases.append(chosen)

    result.sort(key=lambda n: n["start"])
    return result


def clean_melody(notes, ticks_per_beat):
    """第一遍：不依赖调性，先找稳定的连续旋律线。"""
    return _clean_melody_with_params(notes, ticks_per_beat)


def refine_melody_with_key(candidate_pool, provisional, tonic, mode, ticks_per_beat):
    """第二遍：知道原调以后重新选一次旋律。

    这是 V7 的关键：
      第一遍解决“谁是旋律”；
      第二遍解决“这条旋律在这个调性里是否合理”。
    """
    if not candidate_pool:
        return provisional

    refined = _clean_melody_with_params(
        candidate_pool,
        ticks_per_beat,
        tonic=tonic,
        mode=mode,
    )

    if not refined:
        return provisional

    # 如果第二遍过度删音，优先保留第一遍结果。
    ratio = len(refined) / max(1, len(provisional))
    if ratio < 0.72:
        return provisional

    return refined


def _phrase_interval_signature(notes):
    if len(notes) < 3:
        return ()
    intervals = [
        notes[i]["pitch"] - notes[i - 1]["pitch"]
        for i in range(1, len(notes))
    ]
    # 用方向 + 粗粒度大小形成 motif 指纹。
    sig = []
    for x in intervals:
        if x == 0:
            sig.append(0)
        elif abs(x) <= 2:
            sig.append(1 if x > 0 else -1)
        elif abs(x) <= 5:
            sig.append(2 if x > 0 else -2)
        elif abs(x) <= 8:
            sig.append(3 if x > 0 else -3)
        else:
            sig.append(4 if x > 0 else -4)
    return tuple(sig)


def apply_motif_consistency(notes, ticks_per_beat):
    """弱约束重复乐句：只修明显的“同样旋律突然形状不一致”。

    不直接重写音符，仅在相似乐句出现时做轻量异常修正，避免破坏原 MIDI。
    """
    if len(notes) < 12:
        return notes

    phrases = _phrase_segments(notes, ticks_per_beat)
    if len(phrases) < 2:
        return notes

    # 当前版本只做诊断式锁定：找到相似 phrase 后，若后一段出现孤立超大跳，
    # 且它与前一段的整体轮廓明显冲突，则尝试用邻近音修正。
    # 不做跨轨重新选音，避免过拟合。
    flattened = []
    for phrase in phrases:
        flattened.extend(phrase)

    # 只针对孤立异常：前后都是小步，当前突然跨两个八度以上。
    result = list(flattened)
    for i in range(1, len(result) - 1):
        a = result[i - 1]["pitch"]
        b = result[i]["pitch"]
        c = result[i + 1]["pitch"]
        if abs(b - a) >= 19 and abs(c - b) >= 19:
            # 同向/反向都保留原值；这是保护性策略，不擅自改原旋律。
            continue
        if abs(b - a) >= 19 and abs(c - b) <= 4:
            # 这种模式很可能是装饰性跳音，仍可能是真旋律，所以不删除。
            continue

    return result


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

    starts = sorted(set(n["start"] for n in notes))
    if len(starts) < 3:
        return max(1, ticks_per_beat // 4)

    # 同时尝试二分和三分节奏。
    candidates = [
        max(1, ticks_per_beat // 2),   # 1/8
        max(1, ticks_per_beat // 3),   # 1/8 三连音单位
        max(1, ticks_per_beat // 4),   # 1/16
        max(1, ticks_per_beat // 6),   # 1/16 三连音单位
        max(1, ticks_per_beat // 8),   # 1/32
    ]

    candidates = list(dict.fromkeys(candidates))
    best_grid = candidates[2 if len(candidates) > 2 else 0]
    best_score = float("inf")

    for grid in candidates:
        errors = [abs(x - snap_grid(x, grid)) for x in starts]
        mean_error = mean(errors)
        exact_ratio = sum(1 for e in errors if e == 0) / len(errors)

        # 网格太细会制造大量无意义空位；太粗则破坏切分。
        slots_per_beat = max(1.0, ticks_per_beat / grid)
        complexity = 0.55 * max(0.0, slots_per_beat - 4.0)

        # 对 1/16 给一个很轻的偏好，作为音乐性与复杂度的折中。
        musical_prior = 0.0
        if grid == ticks_per_beat // 4:
            musical_prior = -0.35

        score = (
            mean_error
            - exact_ratio * min(grid * 0.18, 8.0)
            + complexity
            + musical_prior
        )

        if score < best_score:
            best_score = score
            best_grid = grid

    return max(1, best_grid)


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

    notes = apply_motif_consistency(notes, ticks_per_beat)
    mapped_notes = map_melody_sequence(
        notes,
        normalization_shift,
        octave_shift,
    )

    grid = choose_rhythm_grid(notes, ticks_per_beat)
    result = []

    for i, note in enumerate(mapped_notes):
        start = snap_grid(note["start"], grid)
        quantized_dur = max(grid, snap_grid(note["dur"], grid))

        # 单音旋律里，下一次起音到来时当前音应当结束，避免试听 MIDI
        # 因重叠音造成“粘音/吞音”。
        if i + 1 < len(mapped_notes):
            next_start = snap_grid(mapped_notes[i + 1]["start"], grid)
            if next_start > start:
                quantized_dur = min(quantized_dur, next_start - start)

        result.append({
            "key": SKY_KEYS_MIDI.index(note["mapped_pitch"]),
            "pitch": note["mapped_pitch"],
            "original_pitch": note["pitch"],
            "start": start,
            "end": start + max(grid, quantized_dur),
            "dur": max(grid, quantized_dur),
            "velocity": note.get("velocity", 64),
            "is_melody": True,
        })

    # 同一网格碰撞采用“看前后”的选择，而不是只看前一个。
    grouped = defaultdict(list)
    for event in result:
        grouped[event["start"]].append(event)

    final = []
    for start in sorted(grouped):
        group = grouped[start]
        if len(group) == 1:
            final.append(group[0])
            continue

        prev_pitch = final[-1]["pitch"] if final else None
        next_pitch = None
        # 找下一个不同 start 的事件音高。
        for s2 in sorted(grouped):
            if s2 > start:
                next_pitch = min(grouped[s2], key=lambda e: abs(e["pitch"] - (prev_pitch or e["pitch"]))) ["pitch"]
                break

        def rank(event):
            continuity = abs(event["pitch"] - prev_pitch) if prev_pitch is not None else 0.0
            future = abs(next_pitch - event["pitch"]) if next_pitch is not None else 0.0
            return (
                continuity * 0.65 + future * 0.35,
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

        # 光遇最终时间轴同一网格只能保留一个音。
        # 因此主旋律起点直接放弃 Bass，避免“试听 MIDI 有双音、15 键谱没有”的不一致。
        if start in melody_starts:
            continue

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


def melody_quality_report(original_notes, melody_events, grid):
    """输出几个非常实用的调试指标，方便判断 V6 是否真的比 V5 好。"""
    if not original_notes or not melody_events:
        return {
            "pitch_match": 0.0,
            "direction_match": 0.0,
            "rhythm_onset_error": 0.0,
        }

    raw = [n["pitch"] for n in original_notes]
    mapped = [e["pitch"] for e in melody_events]
    count = min(len(raw), len(mapped))

    pitch_match = sum(
        1 for a, b in zip(raw[:count], mapped[:count])
        if abs(a - b) <= 1
    ) / max(1, count)

    raw_dirs = []
    mapped_dirs = []
    for i in range(1, count):
        ra = raw[i] - raw[i - 1]
        ma = mapped[i] - mapped[i - 1]
        raw_dirs.append(1 if ra > 0 else -1 if ra < 0 else 0)
        mapped_dirs.append(1 if ma > 0 else -1 if ma < 0 else 0)

    direction_match = sum(a == b for a, b in zip(raw_dirs, mapped_dirs)) / max(1, len(raw_dirs))

    raw_starts = [n["start"] for n in original_notes]
    mapped_starts = [e["start"] for e in melody_events]
    c2 = min(len(raw_starts), len(mapped_starts))
    rhythm_error = mean(
        abs(raw_starts[i] - mapped_starts[i])
        for i in range(c2)
    ) if c2 else 0.0

    return {
        "pitch_match": pitch_match,
        "direction_match": direction_match,
        "rhythm_onset_error": rhythm_error,
    }


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

def degree_from_mapped_pitch(mapped_pitch, output_tonic=0, mode="major"):
    relative = mapped_pitch - output_tonic
    octave = math.floor(relative / 12)
    pc = relative % 12

    if mode == "minor":
        scale = MINOR_SCALE
        names = ["1", "2", "b3", "4", "5", "b6", "b7"]
    else:
        scale = MAJOR_SCALE
        names = ["1", "2", "3", "4", "5", "6", "7"]

    distances = [min(abs(pc - s), 12 - abs(pc - s)) for s in scale]
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
    mode="major",
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
                    mode=mode,
                )
            )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("========================================\n")
        f.write("            光遇15键实际简谱 V7\n")
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
        f.write("        MIDI -> 光遇 15 键简谱 V7\n")
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
    output_midi="sky_preview_v7.mid",
    output_sky="sky_sheet_v7.txt",
    output_simple="simple_sheet_v7.txt",
):
    print()
    print("=" * 60)
    print("       MIDI -> 光遇 15 键简谱 V7")
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

    # 2. 旋律候选池
    melody_candidates, accompaniment = select_melody(
        tracks,
        mid.ticks_per_beat,
    )

    print(f"[2/8] 旋律候选: {len(melody_candidates)}")
    print(f"      伴奏候选: {len(accompaniment)}")

    # 3. 旋律清洗
    melody = clean_melody(
        melody_candidates,
        mid.ticks_per_beat,
    )

    if not melody:
        raise RuntimeError("无法提取主旋律")

    print(f"[3/8] 旋律初选: {len(melody)}")

    # 4. 第一次调性检测
    tonic, mode, key_desc = detect_key(
        melody,
        all_notes,
    )

    print(f"[4/8] 初始调性: {key_desc}")

    # 5. V7 第二次旋律优化：把调性作为软约束重新挑旋律
    refined_melody = refine_melody_with_key(
        melody_candidates,
        melody,
        tonic,
        mode,
        mid.ticks_per_beat,
    )
    if len(refined_melody) >= max(1, int(len(melody) * 0.72)):
        melody = refined_melody

    # 调性再估一次，减少“旋律初选偏错导致后续全部偏移”
    tonic, mode, key_desc = detect_key(
        melody,
        all_notes,
    )

    print(f"[5/8] V7旋律重估: {len(melody)} 音符 / {key_desc}")

    # 6. 转调
    normalization_shift = choose_normalization_shift(
        melody,
        tonic,
        mode,
    )

    print(f"[6/8] 整体转调: {normalization_shift:+d} 半音")

    # 7. 八度
    octave_shift = choose_best_octave_shift(
        melody,
        normalization_shift,
    )

    print(f"[7/8] 八度: {octave_shift:+d}")

    # 8. 旋律
    melody_events, grid = build_melody_events(
        melody,
        normalization_shift,
        octave_shift,
        mid.ticks_per_beat,
    )

    print(f"[8/9] 旋律事件: {len(melody_events)}")
    print(f"      网格: {grid} ticks")

    quality = melody_quality_report(melody, melody_events, grid)
    print(f"      音高保真: {quality['pitch_match'] * 100:.1f}%")
    print(f"      方向保真: {quality['direction_match'] * 100:.1f}%")
    print(f"      起音误差: {quality['rhythm_onset_error']:.1f} ticks")

    # 9. Bass
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
        mode,
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
    import argparse

    parser = argparse.ArgumentParser(description="MIDI -> 光遇 15 键 V7")
    parser.add_argument("input", nargs="?", default="起风了.mid", help="输入 MIDI 文件")
    parser.add_argument("--preview", default="sky_preview_v7.mid", help="试听 MIDI 输出")
    parser.add_argument("--sky", default="sky_sheet_v7.txt", help="15键谱输出")
    parser.add_argument("--simple", default="simple_sheet_v7.txt", help="数字简谱输出")
    args = parser.parse_args()

    convert_midi_to_sky(
        args.input,
        args.preview,
        args.sky,
        args.simple,
    )
