import mido
import math
from collections import Counter, defaultdict
from statistics import mean


# ============================================================
# MIDI → 光遇 15 键简谱转换器 V4
#
# 目标：
#   不是机械地把 MIDI pitch 映射到 15 键
#
#   而是：
#
#       MIDI
#        ↓
#       主旋律提取
#        ↓
#       调性检测
#        ↓
#       整曲转到适合光遇15键的白键调
#        ↓
#       保留原曲音程关系
#        ↓
#       最佳八度
#        ↓
#       非白键最小化吸附
#        ↓
#       节奏量化
#        ↓
#       A1 ~ C5
#
#  目标效果：
#       “对着谱子直接弹，仍然能听出来原曲。”
# ============================================================


# ============================================================
# 光遇 15 键
#
# 物理音高：
#
# C3 D3 E3 F3 G3 A3 B3
# C4 D4 E4 F4 G4 A4 B4
# C5
#
# 对应：
#
# A1 A2 A3 A4 A5 B1 B2
# B3 B4 B5 C1 C2 C3 C4 C5
# ============================================================

SKY_KEYS_MIDI = [
    48, 50, 52, 53, 55, 57, 59,
    60, 62, 64, 65, 67, 69, 71,
    72
]

SKY_KEY_TAGS = [
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
    "C1", "C2", "C3", "C4", "C5"
]


NOTE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B"
]


# ============================================================
# C 大调白键
# ============================================================

WHITE_PITCH_CLASSES = {
    0,   # C
    2,   # D
    4,   # E
    5,   # F
    7,   # G
    9,   # A
    11   # B
}


# ============================================================
# Krumhansl-Schmuckler
# ============================================================

MAJOR_PROFILE = [
    6.35, 2.23, 3.48, 2.33,
    4.38, 4.09, 2.52, 5.19,
    2.39, 3.66, 2.29, 2.88
]

MINOR_PROFILE = [
    6.33, 2.68, 3.52, 5.38,
    2.60, 3.53, 2.54, 4.75,
    3.98, 2.69, 3.34, 3.17
]


# ============================================================
# 工具
# ============================================================

def clamp(value, low, high):
    return max(low, min(high, value))


def pearson(a, b):

    if len(a) != len(b):
        return 0.0

    ma = mean(a)
    mb = mean(b)

    numerator = sum(
        (x - ma) * (y - mb)
        for x, y in zip(a, b)
    )

    da = sum(
        (x - ma) ** 2
        for x in a
    )

    db = sum(
        (y - mb) ** 2
        for y in b
    )

    denominator = math.sqrt(
        da * db
    )

    if denominator == 0:
        return 0.0

    return numerator / denominator


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

            if msg.type not in (
                "note_on",
                "note_off"
            ):
                continue

            channel = getattr(
                msg,
                "channel",
                0
            )

            pitch = getattr(
                msg,
                "note",
                None
            )

            if pitch is None:
                continue

            # MIDI channel 10
            # channel index = 9
            if channel == 9:
                continue

            key = (
                channel,
                pitch
            )

            # note_on
            if (
                msg.type == "note_on"
                and msg.velocity > 0
            ):

                # 异常重复 note_on
                if key in active:

                    old_start = active.pop(
                        key
                    )

                    if current_tick > old_start:

                        notes.append({
                            "pitch": pitch,
                            "start": old_start,
                            "dur": (
                                current_tick
                                - old_start
                            ),
                            "track": track_index,
                            "channel": channel,
                            "velocity": msg.velocity
                        })

                active[key] = current_tick

            # note_off
            else:

                if key not in active:
                    continue

                start = active.pop(key)

                duration = (
                    current_tick
                    - start
                )

                if duration > 0:

                    notes.append({
                        "pitch": pitch,
                        "start": start,
                        "dur": duration,
                        "track": track_index,
                        "channel": channel,
                        "velocity": msg.velocity
                    })

        # MIDI 异常：
        # 没有 note_off
        for (channel, pitch), start in active.items():

            duration = max(
                mid.ticks_per_beat // 4,
                current_tick - start
            )

            notes.append({
                "pitch": pitch,
                "start": start,
                "dur": duration,
                "track": track_index,
                "channel": channel,
                "velocity": 64
            })

        if notes:

            notes.sort(
                key=lambda x: (
                    x["start"],
                    x["pitch"]
                )
            )

            tracks.append(notes)

    return tracks


# ============================================================
# 2. Track 旋律评分
# ============================================================

def score_track(
    notes,
    ticks_per_beat
):

    if not notes:
        return -999999

    pitches = [
        n["pitch"]
        for n in notes
    ]

    starts = [
        n["start"]
        for n in notes
    ]

    durations = [
        n["dur"]
        for n in notes
    ]

    avg_pitch = mean(
        pitches
    )

    pitch_range = (
        max(pitches)
        - min(pitches)
    )

    unique_starts = len(
        set(starts)
    )

    polyphony_rate = (
        1
        -
        unique_starts /
        max(1, len(notes))
    )

    # 短音较多通常更像旋律
    short_count = sum(
        1
        for duration in durations
        if duration
        <= ticks_per_beat // 2
    )

    short_rate = (
        short_count /
        len(notes)
    )

    pitch_score = clamp(
        (avg_pitch - 48) / 48,
        0,
        1
    )

    range_score = clamp(
        pitch_range / 36,
        0,
        1
    )

    density_score = clamp(
        len(notes) / 250,
        0,
        1
    )

    score = (
        pitch_score * 30
        + range_score * 25
        + density_score * 30
        + short_rate * 15
        - polyphony_rate * 40
    )

    return score


# ============================================================
# 3. 自动选择旋律轨
# ============================================================

def select_melody(
    tracks,
    ticks_per_beat
):

    if not tracks:
        return [], []

    if len(tracks) == 1:
        return tracks[0], []

    scored = []

    for index, notes in enumerate(tracks):

        score = score_track(
            notes,
            ticks_per_beat
        )

        scored.append(
            (
                score,
                index,
                notes
            )
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True
    )

    _, melody_index, melody = scored[0]

    accompaniment = []

    for _, index, notes in scored:

        if index != melody_index:
            accompaniment.extend(
                notes
            )

    return melody, accompaniment


# ============================================================
# 4. 旋律清洗
# ============================================================

def clean_melody(
    notes,
    ticks_per_beat
):

    if not notes:
        return []

    # 删除极短噪声
    min_duration = max(
        1,
        ticks_per_beat // 32
    )

    filtered = [
        n
        for n in notes
        if n["dur"] >= min_duration
    ]

    # 同一个时间点可能存在和弦
    # 主旋律优先取最高音
    grouped = defaultdict(list)

    for note in filtered:

        grouped[
            note["start"]
        ].append(note)

    result = []

    for start in sorted(grouped):

        group = grouped[start]

        group.sort(
            key=lambda x: (
                x["pitch"],
                x["dur"]
            ),
            reverse=True
        )

        result.append(
            group[0]
        )

    # 连续重复噪音
    cleaned = []

    for note in result:

        if cleaned:

            previous = cleaned[-1]

            if (
                previous["pitch"]
                == note["pitch"]
                and
                note["start"]
                - previous["start"]
                <= ticks_per_beat // 32
            ):
                continue

        cleaned.append(note)

    return cleaned


# ============================================================
# 5. 调性检测
# ============================================================

def detect_key(
    melody,
    all_notes
):

    # 优先使用旋律
    source = (
        melody
        if len(melody) >= 8
        else all_notes
    )

    weights = [0.0] * 12

    for note in source:

        pitch_class = (
            note["pitch"] % 12
        )

        # 长音更重要
        duration_weight = min(
            note["dur"],
            4 * 480
        ) / 480.0

        # 高音稍微提高
        pitch_weight = clamp(
            (note["pitch"] - 48)
            / 48,
            0,
            1
        )

        weight = (
            duration_weight
            * (
                1
                + pitch_weight * 0.15
            )
        )

        weights[pitch_class] += (
            weight
        )

    best_score = -999999

    best_tonic = 0
    best_mode = "major"

    for tonic in range(12):

        rotated = [
            weights[
                (tonic + i) % 12
            ]
            for i in range(12)
        ]

        major_score = pearson(
            rotated,
            MAJOR_PROFILE
        )

        minor_score = pearson(
            rotated,
            MINOR_PROFILE
        )

        if major_score > best_score:

            best_score = major_score
            best_tonic = tonic
            best_mode = "major"

        if minor_score > best_score:

            best_score = minor_score
            best_tonic = tonic
            best_mode = "minor"

    mode_name = (
        "大调"
        if best_mode == "major"
        else "小调"
    )

    description = (
        f"{NOTE_NAMES[best_tonic]}"
        f" {mode_name}"
    )

    return (
        best_tonic,
        best_mode,
        description
    )


# ============================================================
# 6. 计算“最佳转调”
#
# 核心改动：
#
# 不再：
#
#     degree -> C大调 degree
#
# 而是：
#
#     整首 MIDI 整体平移
#
# 这样可以最大程度保留真实音程。
#
# 大调：
#
#     转到 C 大调白键空间
#
# 小调：
#
#     转到 A 小调白键空间
#
# ============================================================

def choose_normalization_shift(
    notes,
    tonic,
    mode
):

    if not notes:
        return 0

    # --------------------------------------------------------
    # 目标：
    #
    # Major:
    #     tonic -> C
    #
    # Minor:
    #     tonic -> A
    #
    # --------------------------------------------------------

    target_tonic = (
        0
        if mode == "major"
        else 9
    )

    theoretical_shift = (
        target_tonic
        - tonic
    )

    # 在理论最佳值附近搜索
    # 防止极端 MIDI / 调性误判
    candidates = []

    for delta in range(-3, 4):

        shift = (
            theoretical_shift
            + delta
        )

        candidates.append(
            shift
        )

    best_shift = theoretical_shift
    best_score = -999999

    for shift in candidates:

        score = 0.0

        for note in notes:

            p = (
                note["pitch"]
                + shift
            )

            pitch_class = (
                p % 12
            )

            # 白键奖励
            if pitch_class in WHITE_PITCH_CLASSES:

                weight = (
                    1
                    + min(
                        note["dur"] / 480.0,
                        2
                    )
                )

                score += (
                    10 * weight
                )

            else:

                # 黑键罚分
                distance_to_white = min(
                    abs(
                        pitch_class - white
                    )
                    for white in WHITE_PITCH_CLASSES
                )

                score -= (
                    distance_to_white * 5
                )

        # 优先接近理论转调
        score -= (
            abs(
                shift
                - theoretical_shift
            )
            * 3
        )

        if score > best_score:

            best_score = score
            best_shift = shift

    return best_shift


# ============================================================
# 7. 最佳八度
#
# 这一版真正根据“最终 Sky 键位”评价。
# ============================================================

def choose_best_octave_shift(
    notes,
    normalization_shift
):

    if not notes:
        return 0

    best_shift = 0
    best_score = -999999

    for octave_shift in range(
        -4,
        5
    ):

        score = 0.0

        for note in notes:

            pitch = (
                note["pitch"]
                + normalization_shift
                + octave_shift * 12
            )

            # 完全在15键范围
            if 48 <= pitch <= 72:

                weight = (
                    1
                    + min(
                        note["dur"] / 480,
                        2
                    )
                )

                score += (
                    20 * weight
                )

                # 不要太靠边
                if 50 <= pitch <= 70:
                    score += 4

            else:

                distance = (
                    48 - pitch
                    if pitch < 48
                    else pitch - 72
                )

                score -= (
                    distance * 3
                )

            # 白键奖励
            if (
                pitch % 12
                in WHITE_PITCH_CLASSES
            ):
                score += 3

        # 覆盖率
        valid_count = sum(
            1
            for note in notes
            if (
                48
                <=
                note["pitch"]
                + normalization_shift
                + octave_shift * 12
                <=
                72
            )
        )

        coverage = (
            valid_count
            / len(notes)
        )

        score += (
            coverage * 300
        )

        if score > best_score:

            best_score = score
            best_shift = octave_shift

    return best_shift


# ============================================================
# 8. MIDI → 最近白键
#
# 光遇15键没有黑键。
#
# 原曲若出现：
#
# C# / D# / F# / G# / A#
#
# 尽量选择最近白键。
#
# 同距离情况下：
#
#     优先考虑前后旋律方向
# ============================================================

def snap_to_sky_pitch(
    pitch,
    previous_pitch=None,
    next_pitch=None
):

    # 已经是白键
    if (
        pitch % 12
        in WHITE_PITCH_CLASSES
    ):
        return pitch

    candidates = []

    # 最近白键
    for offset in range(-2, 3):

        candidate = pitch + offset

        if (
            candidate % 12
            in WHITE_PITCH_CLASSES
        ):

            distance = abs(
                candidate - pitch
            )

            candidates.append(
                (
                    distance,
                    candidate
                )
            )

    if not candidates:
        return pitch

    min_distance = min(
        x[0]
        for x in candidates
    )

    nearest = [
        candidate
        for distance, candidate
        in candidates
        if distance == min_distance
    ]

    if len(nearest) == 1:
        return nearest[0]

    # --------------------------------------------------------
    # 两边距离相等：
    #
    # 例如 C#：
    #
    #     C 或 D
    #
    # 根据旋律方向判断
    # --------------------------------------------------------

    if (
        previous_pitch is not None
        and next_pitch is not None
    ):

        direction = (
            next_pitch
            - previous_pitch
        )

        if direction > 0:

            higher = [
                x
                for x in nearest
                if x > pitch
            ]

            if higher:
                return higher[0]

        elif direction < 0:

            lower = [
                x
                for x in nearest
                if x < pitch
            ]

            if lower:
                return lower[-1]

    # 默认向下
    lower = [
        x
        for x in nearest
        if x < pitch
    ]

    if lower:
        return lower[-1]

    return nearest[0]


# ============================================================
# 9. MIDI pitch → Sky 键
# ============================================================

def midi_to_sky_key(
    pitch
):

    # 必须是15键之一
    if pitch not in SKY_KEYS_MIDI:

        return None

    return SKY_KEYS_MIDI.index(
        pitch
    )


# ============================================================
# 10. 生成旋律事件
# ============================================================

def build_melody_events(
    notes,
    normalization_shift,
    octave_shift,
    ticks_per_beat
):

    if not notes:
        return []

    # --------------------------------------------------------
    # 推荐 1/16 网格
    # --------------------------------------------------------

    grid = max(
        1,
        ticks_per_beat // 4
    )

    result = []

    for i, note in enumerate(notes):

        raw_pitch = (
            note["pitch"]
            + normalization_shift
            + octave_shift * 12
        )

        previous_pitch = None
        next_pitch = None

        if i > 0:

            previous_pitch = (
                notes[i - 1]["pitch"]
                + normalization_shift
                + octave_shift * 12
            )

        if i + 1 < len(notes):

            next_pitch = (
                notes[i + 1]["pitch"]
                + normalization_shift
                + octave_shift * 12
            )

        # 非白键吸附
        pitch = snap_to_sky_pitch(
            raw_pitch,
            previous_pitch,
            next_pitch
        )

        # 如果整体八度后超范围：
        # 先尝试上下八度局部折叠
        if not (
            48 <= pitch <= 72
        ):

            alternatives = []

            for extra in (
                -24,
                -12,
                12,
                24
            ):

                candidate = (
                    pitch
                    + extra
                )

                if 48 <= candidate <= 72:

                    # 距离原音越近越优先
                    alternatives.append(
                        (
                            abs(extra),
                            candidate
                        )
                    )

            if alternatives:

                alternatives.sort(
                    key=lambda x: x[0]
                )

                pitch = alternatives[0][1]

        key = midi_to_sky_key(
            pitch
        )

        # 仍然无效
        # 极少数极端 MIDI
        if key is None:
            continue

        start = int(
            round(
                note["start"]
                / grid
            ) * grid
        )

        duration = max(
            grid,
            int(
                round(
                    note["dur"]
                    / grid
                ) * grid
            )
        )

        end = (
            start + duration
        )

        result.append({
            "key": key,
            "pitch": pitch,
            "original_pitch": note["pitch"],
            "start": start,
            "end": end,
            "dur": duration,
            "is_melody": True
        })

    return result


# ============================================================
# 11. 伴奏
#
# 默认只取低音，而且非常稀疏。
#
# 原因：
#
# “能听出是什么歌”
#
# 比“把所有和弦塞进去”
# 更重要。
# ============================================================

def build_bass_events(
    accompaniment,
    normalization_shift,
    octave_shift,
    ticks_per_beat,
    melody_events
):

    if not accompaniment:
        return []

    grid = max(
        1,
        ticks_per_beat // 4
    )

    # 每半拍最多一个 bass
    min_interval = (
        ticks_per_beat // 2
    )

    candidates = []

    for note in accompaniment:

        # 只考虑低音
        shifted_pitch = (
            note["pitch"]
            + normalization_shift
            + octave_shift * 12
        )

        if shifted_pitch > 64:
            continue

        pitch = snap_to_sky_pitch(
            shifted_pitch
        )

        # 伴奏如果太低，
        # 尝试拉回 Sky 范围
        while pitch < 48:
            pitch += 12

        while pitch > 72:
            pitch -= 12

        if not (
            48 <= pitch <= 72
        ):
            continue

        key = midi_to_sky_key(
            pitch
        )

        if key is None:
            continue

        # 只接受低音区
        if key > 6:
            continue

        start = int(
            round(
                note["start"]
                / grid
            ) * grid
        )

        candidates.append({
            "key": key,
            "pitch": pitch,
            "original_pitch": note["pitch"],
            "start": start,
            "end": (
                start
                + max(
                    grid,
                    int(
                        round(
                            note["dur"]
                            / grid
                        )
                    )
                )
            ),
            "dur": max(
                grid,
                int(
                    round(
                        note["dur"]
                        / grid
                    )
                )
            ),
            "is_melody": False
        })

    # 同一时间最低音
    grouped = defaultdict(list)

    for event in candidates:

        grouped[
            event["start"]
        ].append(event)

    result = []

    last_time = -999999

    for start in sorted(grouped):

        if (
            start - last_time
            < min_interval
        ):
            continue

        group = grouped[start]

        group.sort(
            key=lambda x:
            x["pitch"]
        )

        result.append(
            group[0]
        )

        last_time = start

    return result


# ============================================================
# 12. 合并旋律 + Bass
# ============================================================

def merge_events(
    melody_events,
    bass_events
):

    grouped = defaultdict(list)

    for event in melody_events:

        grouped[
            event["start"]
        ].append(event)

    for event in bass_events:

        grouped[
            event["start"]
        ].append(event)

    result = []

    for start in sorted(grouped):

        group = grouped[start]

        melody = [
            x
            for x in group
            if x["is_melody"]
        ]

        bass = [
            x
            for x in group
            if not x["is_melody"]
        ]

        # 旋律优先
        if melody:

            melody.sort(
                key=lambda x:
                x["original_pitch"],
                reverse=True
            )

            result.append(
                melody[0]
            )

        # 再考虑低音
        if bass:

            bass.sort(
                key=lambda x:
                x["pitch"]
            )

            bass_event = bass[0]

            if (
                not melody
                or
                bass_event["key"]
                !=
                melody[0]["key"]
            ):

                result.append(
                    bass_event
                )

    return sorted(
        result,
        key=lambda x: (
            x["start"],
            not x["is_melody"]
        )
    )


# ============================================================
# 13. 生成 15 键时间轴
# ============================================================

def build_timeline(
    events,
    ticks_per_beat
):

    if not events:
        return [], 1

    grid = max(
        1,
        ticks_per_beat // 4
    )

    max_end = max(
        e["end"]
        for e in events
    )

    slots = (
        int(
            math.ceil(
                max_end / grid
            )
        )
        + 1
    )

    timeline = [
        None
        for _ in range(slots)
    ]

    for event in events:

        slot = int(
            round(
                event["start"]
                / grid
            )
        )

        if not (
            0 <= slot < slots
        ):
            continue

        current = timeline[slot]

        if current is None:

            timeline[slot] = event

        else:

            # 旋律优先
            if (
                event["is_melody"]
                and
                not current["is_melody"]
            ):
                timeline[slot] = event

            elif (
                event["is_melody"]
                and
                current["is_melody"]
                and
                event["original_pitch"]
                > current["original_pitch"]
            ):
                timeline[slot] = event

    return timeline, grid


# ============================================================
# 14. 输出 ABC1/5 风格 TXT
# ============================================================

def write_sky_sheet(
    timeline,
    grid,
    ticks_per_beat,
    output_file,
    title,
    original_key,
    normalization_shift,
    octave_shift,
    bpm
):

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "========================================\n"
        )

        f.write(
            "      MIDI → 光遇 15 键简谱\n"
        )

        f.write(
            "========================================\n"
        )

        f.write(
            f"歌曲: {title}\n"
        )

        f.write(
            f"原调: {original_key}\n"
        )

        f.write(
            f"整体转调: "
            f"{normalization_shift:+d} 半音\n"
        )

        f.write(
            f"八度调整: "
            f"{octave_shift:+d} 八度\n"
        )

        f.write(
            f"BPM: {bpm:.2f}\n"
        )

        f.write(
            "网格: 1/16\n"
        )

        f.write(
            "\n"
        )

        f.write(
            "15键映射:\n"
        )

        for i, tag in enumerate(
            SKY_KEY_TAGS
        ):

            f.write(
                f"{i+1:02d}={tag}"
                f"({SKY_KEYS_MIDI[i]})  "
            )

            if (
                i + 1
            ) % 5 == 0:

                f.write(
                    "\n"
                )

        f.write(
            "\n"
        )

        f.write(
            "说明: '.' = 等待一个16分音符时间\n"
        )

        f.write(
            "========================================\n\n"
        )

        tokens = []

        for event in timeline:

            if event is None:

                tokens.append(".")

            else:

                tokens.append(
                    SKY_KEY_TAGS[
                        event["key"]
                    ]
                )

        # 每16格一行
        for i in range(
            0,
            len(tokens),
            16
        ):

            chunk = tokens[
                i:i + 16
            ]

            f.write(
                " ".join(chunk)
                + "\n"
            )


# ============================================================
# 15. 输出数字简谱
#
# 注意：
#
# 这里的数字是“实际演奏所对应的音阶级数”，
# 不是 MIDI 原调的绝对 pitch。
#
# Major:
#   1 2 3 4 5 6 7
#
# Minor:
#   1 2 b3 4 5 b6 b7
#
# 高低音通过括号表示：
#
#   [1] = 低音1
#    1  = 中音1
#   {1} = 高音1
# ============================================================

def simple_degree(
    original_pitch,
    tonic,
    mode
):

    # 相对原调主音
    relative = (
        original_pitch
        - tonic
    )

    # pitch class
    pc = relative % 12

    if mode == "major":

        scale = [
            0, 2, 4, 5,
            7, 9, 11
        ]

        names = [
            "1", "2", "3", "4",
            "5", "6", "7"
        ]

    else:

        scale = [
            0, 2, 3, 5,
            7, 8, 10
        ]

        names = [
            "1", "2", "b3", "4",
            "5", "b6", "b7"
        ]

    # 最近音级
    distances = [
        min(
            abs(pc - s),
            12 - abs(pc - s)
        )
        for s in scale
    ]

    degree = distances.index(
        min(distances)
    )

    octave = (
        relative // 12
    )

    token = names[degree]

    if octave < 0:
        token = (
            "[" * min(
                abs(octave),
                2
            )
            + token
            + "]" * min(
                abs(octave),
                2
            )
        )

    elif octave > 0:
        token = (
            "{"
            + token
            + "}"
        )

    return token


def write_simple_sheet(
    events,
    ticks_per_beat,
    output_file,
    title,
    tonic,
    mode,
    original_key
):

    if not events:
        return

    grid = max(
        1,
        ticks_per_beat // 4
    )

    max_end = max(
        e["end"]
        for e in events
    )

    slot_count = (
        int(
            math.ceil(
                max_end / grid
            )
        )
        + 1
    )

    timeline = [
        None
        for _ in range(slot_count)
    ]

    for event in events:

        slot = int(
            round(
                event["start"]
                / grid
            )
        )

        if not (
            0 <= slot < slot_count
        ):
            continue

        # 旋律优先
        if (
            timeline[slot]
            is None
        ):

            timeline[slot] = event

        else:

            if (
                event["is_melody"]
                and
                not timeline[slot][
                    "is_melody"
                ]
            ):

                timeline[slot] = event

    tokens = []

    for event in timeline:

        if event is None:

            tokens.append(".")

        else:

            tokens.append(
                simple_degree(
                    event["original_pitch"],
                    tonic,
                    mode
                )
            )

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "========================================\n"
        )

        f.write(
            "             首调数字简谱\n"
        )

        f.write(
            "========================================\n"
        )

        f.write(
            f"歌曲: {title}\n"
        )

        f.write(
            f"原调: {original_key}\n"
        )

        f.write(
            "\n"
        )

        f.write(
            "说明:\n"
        )

        f.write(
            "1 2 3 4 5 6 7 = 中音\n"
        )

        f.write(
            "[1] = 低音\n"
        )

        f.write(
            "{1} = 高音\n"
        )

        f.write(
            ". = 空拍\n"
        )

        f.write(
            "\n"
        )

        for i in range(
            0,
            len(tokens),
            16
        ):

            f.write(
                " ".join(
                    tokens[
                        i:i + 16
                    ]
                )
                + "\n"
            )


# ============================================================
# 16. 输出试听 MIDI
# ============================================================

def export_preview_midi(
    events,
    ticks_per_beat,
    output_file
):

    mid = mido.MidiFile(
        ticks_per_beat=ticks_per_beat
    )

    track = mido.MidiTrack()

    mid.tracks.append(
        track
    )

    midi_events = []

    for event in events:

        velocity = (
            100
            if event["is_melody"]
            else 55
        )

        midi_events.append(
            (
                event["start"],
                1,
                event["pitch"],
                velocity
            )
        )

        midi_events.append(
            (
                event["end"],
                0,
                event["pitch"],
                0
            )
        )

    midi_events.sort(
        key=lambda x: (
            x[0],
            x[1]
        )
    )

    last_tick = 0

    for tick, typ, pitch, velocity in midi_events:

        delta = max(
            0,
            tick - last_tick
        )

        if typ == 1:

            msg = mido.Message(
                "note_on",
                note=pitch,
                velocity=velocity,
                time=delta
            )

        else:

            msg = mido.Message(
                "note_off",
                note=pitch,
                velocity=0,
                time=delta
            )

        track.append(msg)

        last_tick = tick

    mid.save(
        output_file
    )


# ============================================================
# 17. 获取 BPM
# ============================================================

def get_bpm(mid):

    try:

        for track in mid.tracks:

            for msg in track:

                if msg.type == "set_tempo":

                    return mido.tempo2bpm(
                        msg.tempo
                    )

    except Exception:
        pass

    return 120.0


# ============================================================
# 18. 主转换器
# ============================================================

def convert_midi_to_sky(
    input_file,
    output_midi="sky_preview.mid",
    output_sky="sky_sheet.txt",
    output_simple="simple_sheet.txt"
):

    print()
    print("=" * 60)
    print(
        "       MIDI → 光遇 15 键简谱 V4"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # MIDI
    # --------------------------------------------------------

    mid = mido.MidiFile(
        input_file
    )

    print(
        f"文件: {input_file}"
    )

    print(
        f"TPB: {mid.ticks_per_beat}"
    )

    bpm = get_bpm(mid)

    print(
        f"BPM: {bpm:.2f}"
    )

    # --------------------------------------------------------
    # 提取 Track
    # --------------------------------------------------------

    tracks = extract_tracks(
        mid
    )

    if not tracks:

        raise RuntimeError(
            "MIDI 中没有有效音符"
        )

    all_notes = [
        note
        for track in tracks
        for note in track
    ]

    print(
        f"[1/8] 总音符: "
        f"{len(all_notes)}"
    )

    # --------------------------------------------------------
    # 旋律
    # --------------------------------------------------------

    melody, accompaniment = (
        select_melody(
            tracks,
            mid.ticks_per_beat
        )
    )

    print(
        f"[2/8] 旋律候选: "
        f"{len(melody)}"
    )

    print(
        f"      伴奏候选: "
        f"{len(accompaniment)}"
    )

    # --------------------------------------------------------
    # 清洗
    # --------------------------------------------------------

    melody = clean_melody(
        melody,
        mid.ticks_per_beat
    )

    print(
        f"[3/8] 旋律清洗: "
        f"{len(melody)}"
    )

    if not melody:

        raise RuntimeError(
            "无法提取主旋律"
        )

    # --------------------------------------------------------
    # 调性
    # --------------------------------------------------------

    tonic, mode, key_desc = detect_key(
        melody,
        all_notes
    )

    print(
        f"[4/8] 原调: {key_desc}"
    )

    # --------------------------------------------------------
    # 转到适合15键的白键调
    # --------------------------------------------------------

    normalization_shift = (
        choose_normalization_shift(
            melody,
            tonic,
            mode
        )
    )

    print(
        f"[5/8] 整体转调: "
        f"{normalization_shift:+d} 半音"
    )

    # --------------------------------------------------------
    # 八度
    # --------------------------------------------------------

    octave_shift = (
        choose_best_octave_shift(
            melody,
            normalization_shift
        )
    )

    print(
        f"[6/8] 八度: "
        f"{octave_shift:+d}"
    )

    # --------------------------------------------------------
    # 旋律
    # --------------------------------------------------------

    melody_events = build_melody_events(
        melody,
        normalization_shift,
        octave_shift,
        mid.ticks_per_beat
    )

    print(
        f"[7/8] 旋律事件: "
        f"{len(melody_events)}"
    )

    # --------------------------------------------------------
    # Bass
    # --------------------------------------------------------

    bass_events = build_bass_events(
        accompaniment,
        normalization_shift,
        octave_shift,
        mid.ticks_per_beat,
        melody_events
    )

    print(
        f"      Bass事件: "
        f"{len(bass_events)}"
    )

    # --------------------------------------------------------
    # 合并
    # --------------------------------------------------------

    final_events = merge_events(
        melody_events,
        bass_events
    )

    print(
        f"[8/8] 最终事件: "
        f"{len(final_events)}"
    )

    # --------------------------------------------------------
    # 时间轴
    # --------------------------------------------------------

    timeline, grid = build_timeline(
        final_events,
        mid.ticks_per_beat
    )

    # --------------------------------------------------------
    # Sky 15键
    # --------------------------------------------------------

    write_sky_sheet(
        timeline,
        grid,
        mid.ticks_per_beat,
        output_sky,
        input_file,
        key_desc,
        normalization_shift,
        octave_shift,
        bpm
    )

    # --------------------------------------------------------
    # 数字简谱
    # --------------------------------------------------------

    write_simple_sheet(
        final_events,
        mid.ticks_per_beat,
        output_simple,
        input_file,
        tonic,
        mode,
        key_desc
    )

    # --------------------------------------------------------
    # 试听 MIDI
    # --------------------------------------------------------

    export_preview_midi(
        final_events,
        mid.ticks_per_beat,
        output_midi
    )

    print()
    print("=" * 60)
    print("转换完成！")
    print("=" * 60)
    print(
        f"原曲调性    : {key_desc}"
    )
    print(
        f"整体转调    : "
        f"{normalization_shift:+d} 半音"
    )
    print(
        f"八度调整    : "
        f"{octave_shift:+d}"
    )
    print(
        f"最终音符    : "
        f"{len(final_events)}"
    )
    print()
    print(
        f"试听 MIDI   : {output_midi}"
    )
    print(
        f"15键谱      : {output_sky}"
    )
    print(
        f"数字简谱    : {output_simple}"
    )
    print("=" * 60)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    convert_midi_to_sky(
        "起风了.mid",
        "sky_preview.mid",
        "sky_sheet.txt",
        "simple_sheet.txt"
    )
 
