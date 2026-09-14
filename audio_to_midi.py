#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""MP3/WAV/FLAC -> 初步清洗 MIDI

用途：
    第一阶段：音频 -> 高质量、较干净、尽量保留复音结构的 MIDI
    第二阶段：由外部程序负责 MIDI -> 光遇 15 键

本程序明确不做：
    - 15 键映射
    - 音域压缩
    - 八度强制映射
    - 单旋律强制提取
    - 大规模删除和弦/低音

核心策略：
    Basic Pitch -> 基础过滤 -> 自适应弱音过滤 -> 同音碎片合并
    -> 同音重叠修复 -> 保守泛音伪影清理 -> 时间窗口孤立音清理
    -> 极端密度软限制 -> 基于真实 Beat 的动态量化 -> MIDI 重建
"""

import argparse
import bisect
import logging
import math
import os
import sys
import time
import warnings
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}


@dataclass
class NoteEvent:
    start: float
    end: float
    pitch: int
    velocity: int
    amplitude: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def is_audio_file(filepath: str) -> bool:
    if not filepath:
        return False
    _, ext = os.path.splitext(filepath.lower())
    return ext in AUDIO_EXTENSIONS


# ============================================================
# BPM / Beat
# ============================================================

def _normalize_tempo(value: float, default: float) -> float:
    """将异常 BPM 限制到合理范围，但不擅自把 200 BPM 改成 100 BPM。"""
    if not math.isfinite(value) or value <= 0:
        return default
    return clamp(float(value), 40.0, 240.0)


def detect_tempo_and_beats(
    audio_path: str,
    default_bpm: float = 120.0,
) -> Tuple[float, List[float]]:
    """检测 BPM 和实际 beat 时间。"""
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(
            audio_path,
            sr=22050,
            mono=True,
            duration=None,
        )

        if y is None or len(y) == 0:
            return default_bpm, []

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env,
            sr=sr,
            trim=False,
        )

        tempo_arr = np.atleast_1d(tempo)
        detected = float(tempo_arr[0]) if len(tempo_arr) else default_bpm
        detected = _normalize_tempo(detected, default_bpm)

        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        beat_times = [
            float(x)
            for x in beat_times
            if math.isfinite(float(x)) and float(x) >= 0
        ]

        # 去重并确保单调
        clean_beats: List[float] = []
        for t in beat_times:
            if not clean_beats or t - clean_beats[-1] > 1e-6:
                clean_beats.append(t)

        return round(detected, 2), clean_beats
    except Exception:
        return default_bpm, []


def _tempo_candidate_score(
    notes: List[NoteEvent],
    beat_times: List[float],
    bpm: float,
    subdivisions: int = 4,
) -> float:
    """比较 BPM/2、BPM、BPM*2 等候选，选择更符合 note onset 的解释。

    这里只用于检测异常倍速，不用于强制量化所有音符。
    分数越高越好。
    """
    if len(notes) < 8 or len(beat_times) < 2 or bpm <= 0:
        return -1.0

    # 使用第一拍作为相位锚点，并按候选 BPM 生成严格网格。
    step = 60.0 / bpm / subdivisions
    if step <= 0:
        return -1.0

    origin = beat_times[0]
    max_error = step * 0.45
    matched = 0
    weighted_error = 0.0

    for note in notes:
        x = (note.start - origin) / step
        nearest = round(x)
        grid_t = origin + nearest * step
        error = abs(note.start - grid_t)

        if error <= max_error:
            # 强音和较长音影响稍大，避免大量微弱噪音主导选择。
            weight = 0.5 + 0.5 * clamp(note.amplitude, 0.0, 1.0)
            matched += 1
            weighted_error += error * weight

    if matched == 0:
        return 0.0

    coverage = matched / max(1, len(notes))
    mean_error = weighted_error / max(1e-9, matched)
    error_score = 1.0 - clamp(mean_error / max_error, 0.0, 1.0)

    # 适度惩罚不合理 BPM，避免候选漂移过大。
    range_penalty = 1.0 if 50.0 <= bpm <= 210.0 else 0.85
    return (coverage * 0.65 + error_score * 0.35) * range_penalty




def adjust_beats_for_tempo_ratio(
    beat_times: List[float],
    from_bpm: float,
    to_bpm: float,
) -> List[float]:
    """当 BPM 被判定为半速/倍速时，同步修正 quantization beat 网格。

    例如：
        from=120, to=60  -> 每隔一个 beat 取一次
        from=120, to=240 -> 在每两个 beat 之间补中点

    仅处理接近 0.5x/1x/2x 的情况，其余保持原 beat。
    """
    if len(beat_times) < 2 or from_bpm <= 0 or to_bpm <= 0:
        return beat_times

    ratio = to_bpm / from_bpm

    if 0.47 <= ratio <= 0.53:
        result = beat_times[::2]
        if len(result) >= 2:
            return result
        return beat_times

    if 1.88 <= ratio <= 2.12:
        result: List[float] = []
        for i in range(len(beat_times) - 1):
            a = beat_times[i]
            b = beat_times[i + 1]
            if b <= a:
                continue
            result.append(a)
            result.append((a + b) * 0.5)
        result.append(beat_times[-1])
        return result

    return beat_times

def choose_tempo_candidate(
    detected_bpm: float,
    beat_times: List[float],
    notes: List[NoteEvent],
) -> float:
    """在 BPM/2、BPM、BPM*2 中做轻量校验，避免半速/倍速误判。"""
    # 若检测速度处于常见流行音乐速度区间 (65 ~ 175 BPM)，优先信任 Librosa 周期分析，避免误判减半/翻倍
    if 65.0 <= detected_bpm <= 175.0:
        return round(detected_bpm, 2)

    if not beat_times or len(notes) < 8:
        return detected_bpm

    candidates = []
    for candidate in (
        detected_bpm / 2.0,
        detected_bpm,
        detected_bpm * 2.0,
    ):
        if 40.0 <= candidate <= 240.0:
            candidates.append(candidate)

    if not candidates:
        return detected_bpm

    scored = [
        (c, _tempo_candidate_score(notes, beat_times, c))
        for c in candidates
    ]
    best_bpm, best_score = max(scored, key=lambda x: x[1])
    detected_score = next((s for c, s in scored if abs(c - detected_bpm) < 1e-6), -1.0)

    # 只有候选明显优于原始检测才切换，防止过度纠正真实高速/低速歌曲。
    if best_bpm != detected_bpm and best_score >= detected_score + 0.15:
        return round(best_bpm, 2)

    return round(detected_bpm, 2)


# ============================================================
# Basic Pitch -> 内部 NoteEvent
# ============================================================

def convert_note_events(note_events: Optional[Sequence]) -> List[NoteEvent]:
    """兼容 Basic Pitch 4 元组/5 元组事件格式：
        (start, end, pitch, amplitude)
        (start, end, pitch, amplitude, pitch_bends)
    """
    result: List[NoteEvent] = []
    if not note_events:
        return result

    for event in note_events:
        try:
            if len(event) < 4:
                continue

            start = float(event[0])
            end = float(event[1])
            pitch = int(round(float(event[2])))
            amplitude = float(event[3])

            if not all(math.isfinite(x) for x in (start, end, amplitude)):
                continue
            if end <= start or pitch < 0 or pitch > 127:
                continue

            amplitude = clamp(amplitude, 0.0, 1.0)
            velocity = int(round(clamp(amplitude * 127.0 * 1.15, 1.0, 127.0)))

            result.append(NoteEvent(start, end, pitch, velocity, amplitude))
        except (TypeError, ValueError, IndexError):
            continue

    result.sort(key=lambda n: (n.start, n.pitch, n.end))
    return result


# ============================================================
# 清洗 1：基础过滤
# ============================================================

def filter_basic_notes(
    notes: List[NoteEvent],
    min_duration: float = 0.075,
    min_amplitude: float = 0.055,
) -> List[NoteEvent]:
    """删除明显碎片，但保持足够宽松，避免吃掉短旋律音。"""
    return [
        n for n in notes
        if n.duration >= min_duration and n.amplitude >= min_amplitude
    ]


# ============================================================
# 清洗 2：自适应弱音过滤
# ============================================================

def adaptive_amplitude_filter(
    notes: List[NoteEvent],
    percentile: float = 8.0,
    max_threshold: float = 0.12,
) -> List[NoteEvent]:
    """按当前歌曲响度分布轻度删除最底部异常弱音。"""
    if len(notes) < 20:
        return notes

    try:
        import numpy as np

        amplitudes = np.array([n.amplitude for n in notes], dtype=np.float32)
        threshold = float(np.percentile(amplitudes, percentile))
        threshold = min(threshold, max_threshold)
        return [n for n in notes if n.amplitude >= threshold]
    except Exception:
        return notes


# ============================================================
# 清洗 3：同音碎片合并
# ============================================================

def merge_same_pitch_notes(
    notes: List[NoteEvent],
    max_gap: float = 0.055,
) -> List[NoteEvent]:
    """合并同音高、时间间隙极短的碎裂音。"""
    if not notes:
        return []

    grouped = {}
    for n in notes:
        grouped.setdefault(n.pitch, []).append(n)

    merged: List[NoteEvent] = []
    for pitch, pitch_notes in grouped.items():
        pitch_notes.sort(key=lambda n: (n.start, n.end))
        current = pitch_notes[0]

        for nxt in pitch_notes[1:]:
            gap = nxt.start - current.end
            if gap <= max_gap:
                d1, d2 = current.duration, nxt.duration
                total = d1 + d2
                amp = ((current.amplitude * d1 + nxt.amplitude * d2) / total) if total > 0 else max(current.amplitude, nxt.amplitude)
                end = max(current.end, nxt.end)
                current = NoteEvent(
                    current.start,
                    end,
                    pitch,
                    int(round(clamp(amp * 127.0 * 1.15, 1.0, 127.0))),
                    amp,
                )
            else:
                merged.append(current)
                current = nxt
        merged.append(current)

    merged.sort(key=lambda n: (n.start, n.pitch, n.end))
    return merged


# ============================================================
# 清洗 4：同音重叠修复（状态安全版）
# ============================================================

def clean_same_pitch_overlaps(
    notes: List[NoteEvent],
    overlap_tolerance: float = 0.035,
) -> List[NoteEvent]:
    """安全处理同音重叠，不在遍历中丢失 previous 状态。"""
    if not notes:
        return []

    grouped = {}
    for n in notes:
        grouped.setdefault(n.pitch, []).append(n)

    result: List[NoteEvent] = []

    for pitch, pitch_notes in grouped.items():
        pitch_notes.sort(key=lambda n: (n.start, n.end))
        cleaned: List[NoteEvent] = []

        for current in pitch_notes:
            if not cleaned:
                cleaned.append(current)
                continue

            previous = cleaned[-1]
            overlap = previous.end - current.start

            if overlap <= 0:
                cleaned.append(current)
                continue

            if overlap <= overlap_tolerance:
                # 轻微重叠：缩短 previous，但 current 一定保留。
                new_end = max(previous.start + 0.02, current.start)
                if new_end <= previous.start:
                    cleaned.pop()
                else:
                    cleaned[-1] = NoteEvent(
                        previous.start,
                        new_end,
                        previous.pitch,
                        previous.velocity,
                        previous.amplitude,
                    )
                cleaned.append(current)
                continue

            # 明显重叠：只有“很短 + 明显更弱”的 current 才删除。
            if current.duration < 0.10 and current.amplitude < previous.amplitude * 0.70:
                continue

            # 否则保留，真实重复击键不能因为重叠规则误删。
            cleaned.append(current)

        result.extend(cleaned)

    result.sort(key=lambda n: (n.start, n.pitch, n.end))
    return result


# ============================================================
# 清洗 5：基于时间窗口的孤立异常音
# ============================================================

def _time_window_slice(
    notes: List[NoteEvent],
    start_times: List[float],
    center: float,
    window: float,
) -> List[NoteEvent]:
    left = bisect.bisect_left(start_times, center - window)
    right = bisect.bisect_right(start_times, center + window)
    return notes[left:right]


def remove_obvious_isolated_notes(
    notes: List[NoteEvent],
    time_window: float = 0.22,
    weak_ratio: float = 0.68,
) -> List[NoteEvent]:
    """只清理很弱、很短、时间上孤立且音高非常离群的音符。"""
    if len(notes) < 8:
        return notes

    notes = sorted(notes, key=lambda n: (n.start, n.pitch))
    start_times = [n.start for n in notes]
    result: List[NoteEvent] = []

    for note in notes:
        nearby = _time_window_slice(notes, start_times, note.start, time_window)
        nearby = [n for n in nearby if n is not note]

        if len(nearby) < 2:
            result.append(note)
            continue

        stronger = [n for n in nearby if n.amplitude >= note.amplitude]

        if note.duration < 0.11 and len(stronger) >= 2:
            max_amp = max(n.amplitude for n in stronger)
            if note.amplitude < max_amp * weak_ratio:
                # 用局部中位音高比平均值更抗和弦异常值。
                pitches = sorted(n.pitch for n in stronger)
                median_pitch = pitches[len(pitches) // 2]
                if abs(note.pitch - median_pitch) >= 12:
                    continue

        result.append(note)

    return result


# ============================================================
# 清洗 6：保守泛音 Ghost Note
# ============================================================

def remove_harmonic_ghost_notes(
    notes: List[NoteEvent],
    max_start_gap: float = 0.025,
    amplitude_ratio: float = 0.30,
    min_base_amplitude: float = 0.42,
) -> List[NoteEvent]:
    """保守删除疑似同起音泛音伪影。

    只考虑 +12 / +19 半音，而且必须满足：
        - 基音很强
        - 候选音显著更弱
        - 几乎同时开始
        - 时长相近
        - 没有其它较强和弦音支持

    真实八度/五度一般不会同时满足这些条件，因此不会轻易被删除。
    """
    if len(notes) < 2:
        return notes

    notes = sorted(notes, key=lambda n: (n.start, n.pitch))
    start_times = [n.start for n in notes]
    remove_ids = set()

    for base in notes:
        if base.amplitude < min_base_amplitude:
            continue

        left = bisect.bisect_left(start_times, base.start - max_start_gap)
        right = bisect.bisect_right(start_times, base.start + max_start_gap)
        neighbors = notes[left:right]

        for other in neighbors:
            if other is base or id(other) in remove_ids:
                continue
            if other.pitch not in (base.pitch + 12, base.pitch + 19):
                continue

            if other.amplitude > base.amplitude * amplitude_ratio:
                continue

            duration_ratio = other.duration / max(base.duration, 0.02)
            if not 0.45 <= duration_ratio <= 1.55:
                continue

            # 同时出现的其他强音通常意味着真实和弦，宁愿保留。
            chord_neighbors = [
                n for n in neighbors
                if n is not base
                and n is not other
                and n.amplitude > base.amplitude * 0.45
            ]
            if chord_neighbors:
                continue

            remove_ids.add(id(other))

    return [n for n in notes if id(n) not in remove_ids]


# ============================================================
# 清洗 7：极端音符密度软限制
# ============================================================

def limit_extreme_note_density(
    notes: List[NoteEvent],
    window: float = 0.030,
    max_notes: int = 7,
) -> List[NoteEvent]:
    """只处理极端密集音簇，不做普通和弦压缩。"""
    if not notes or len(notes) <= max_notes:
        return notes

    notes = sorted(notes, key=lambda n: (n.start, -n.amplitude, n.pitch))
    start_times = [n.start for n in notes]
    keep_ids = {id(n) for n in notes}

    # 极端密集区的候选集合可能重叠；先标记需要压缩的索引。
    crowded_ids = set()
    for i, note in enumerate(notes):
        left = bisect.bisect_left(start_times, note.start - window)
        right = bisect.bisect_right(start_times, note.start + window)
        group = notes[left:right]
        if len(group) > max_notes:
            crowded_ids.update(id(n) for n in group)

    if not crowded_ids:
        return notes

    crowded = [n for n in notes if id(n) in crowded_ids]
    ranked = sorted(
        crowded,
        key=lambda n: (n.amplitude, n.duration),
        reverse=True,
    )

    # 保留强音，同时尽量覆盖不同音高区域，避免密集簇只剩同八度。
    selected: List[NoteEvent] = []
    selected_pitches: List[int] = []
    for n in ranked:
        if len(selected) >= max_notes:
            break
        # 前几名直接保留；之后优先音高距离较大的，提升复音覆盖。
        if len(selected) >= 3 and selected_pitches:
            if max(abs(n.pitch - p) for p in selected_pitches) < 5:
                continue
        selected.append(n)
        selected_pitches.append(n.pitch)

    # 如果多样性约束导致未凑够，按强度补齐。
    if len(selected) < max_notes:
        selected_ids = {id(n) for n in selected}
        for n in ranked:
            if id(n) not in selected_ids:
                selected.append(n)
                selected_ids.add(id(n))
                if len(selected) >= max_notes:
                    break

    keep_ids -= crowded_ids
    keep_ids.update(id(n) for n in selected)

    return [n for n in notes if id(n) in keep_ids]


# ============================================================
# Beat Grid：真正动态插值
# ============================================================

def build_quantize_grid(
    beat_times: List[float],
    duration: float,
    subdivisions: int = 4,
) -> List[float]:
    """在每两个实际 beat 之间动态插值，不使用全曲固定 step。"""
    if len(beat_times) < 2 or duration <= 0 or subdivisions < 1:
        return []

    beats = sorted(
        x for x in beat_times
        if math.isfinite(x) and 0.0 <= x <= duration + 1.0
    )
    if len(beats) < 2:
        return []

    grid: List[float] = []

    for i in range(len(beats) - 1):
        a = beats[i]
        b = beats[i + 1]
        if b <= a:
            continue

        interval = b - a
        for j in range(subdivisions):
            t = a + interval * (j / float(subdivisions))
            if 0.0 <= t <= duration:
                grid.append(t)

    if beats[-1] <= duration:
        grid.append(beats[-1])

    result: List[float] = []
    for t in grid:
        if not result or t - result[-1] > 1e-7:
            result.append(t)
    return result


def nearest_grid_value(value: float, grid: List[float]) -> Optional[float]:
    if not grid:
        return None

    idx = bisect.bisect_left(grid, value)
    candidates = []
    if idx < len(grid):
        candidates.append(grid[idx])
    if idx > 0:
        candidates.append(grid[idx - 1])
    return min(candidates, key=lambda x: abs(x - value)) if candidates else None


def intelligent_quantize(
    notes: List[NoteEvent],
    beat_times: List[float],
    subdivisions: int = 4,
    max_snap_ratio: float = 0.22,
    strength: float = 0.65,
) -> List[NoteEvent]:
    """保守地向动态 Beat 网格吸附，避免把自由节奏硬掰直。"""
    if not notes or len(beat_times) < 2:
        return notes

    strength = clamp(strength, 0.0, 1.0)
    duration = max(n.end for n in notes)
    grid = build_quantize_grid(beat_times, duration, subdivisions)
    if not grid:
        return notes

    # 动态网格没有单一固定 step；局部 step 用相邻 grid 的中位数估计。
    # 量化阈值按当前位置的局部网格间隔决定。
    result: List[NoteEvent] = []

    for note in notes:
        nearest_start = nearest_grid_value(note.start, grid)
        new_start = note.start

        if nearest_start is not None:
            idx = bisect.bisect_left(grid, nearest_start)
            local_neighbors = []
            if idx > 0:
                local_neighbors.append(grid[idx] - grid[idx - 1])
            if idx + 1 < len(grid):
                local_neighbors.append(grid[idx + 1] - grid[idx])

            local_step = min(local_neighbors) if local_neighbors else 0.125
            max_distance = local_step * max_snap_ratio

            if abs(nearest_start - note.start) <= max_distance:
                new_start += (nearest_start - note.start) * strength

        # End 量化明显保守于 start，避免改变自然长音。
        nearest_end = nearest_grid_value(note.end, grid)
        new_end = note.end

        if nearest_end is not None:
            idx = bisect.bisect_left(grid, nearest_end)
            local_neighbors = []
            if idx > 0:
                local_neighbors.append(grid[idx] - grid[idx - 1])
            if idx + 1 < len(grid):
                local_neighbors.append(grid[idx + 1] - grid[idx])
            local_step = min(local_neighbors) if local_neighbors else 0.125
            max_distance = local_step * max_snap_ratio

            if (
                abs(nearest_end - note.end) <= max_distance
                and abs(nearest_end - note.end) <= note.duration * 0.35
            ):
                new_end += (nearest_end - note.end) * strength

        new_start = max(0.0, new_start)
        new_end = max(new_start + 0.035, new_end)

        result.append(NoteEvent(
            new_start,
            new_end,
            note.pitch,
            note.velocity,
            note.amplitude,
        ))

    result.sort(key=lambda n: (n.start, n.pitch, n.end))
    return result


# ============================================================
# 最终安全检查
# ============================================================

def final_note_cleanup(
    notes: List[NoteEvent],
    min_duration: float = 0.055,
) -> List[NoteEvent]:
    return [
        n for n in sorted(notes, key=lambda x: (x.start, x.pitch, x.end))
        if n.end > n.start and n.duration >= min_duration
    ]


# ============================================================
# MIDI 重建
# ============================================================

def build_clean_midi(notes: List[NoteEvent], bpm: float = 120.0):
    """重新构建纯净 MIDI，只写入清洗后的音符。"""
    try:
        import pretty_midi
    except ImportError as exc:
        raise RuntimeError(
            "缺少 pretty_midi，请安装：pip install pretty_midi"
        ) from exc

    midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm))
    instrument = pretty_midi.Instrument(program=0, name="Clean Piano")

    for n in notes:
        instrument.notes.append(
            pretty_midi.Note(
                velocity=int(clamp(n.velocity, 1, 127)),
                pitch=int(clamp(n.pitch, 0, 127)),
                start=float(n.start),
                end=float(n.end),
            )
        )

    # 按时间/音高排序，使部分 MIDI 软件显示更稳定。
    instrument.notes.sort(key=lambda n: (n.start, n.pitch, n.end))
    midi.instruments.append(instrument)
    return midi


# ============================================================
# 完整转换
# ============================================================

def convert_audio_to_midi(
    audio_path: str,
    output_midi_path: Optional[str] = None,
    bpm: Optional[float] = None,
    onset_threshold: float = 0.55,
    frame_threshold: float = 0.30,
    minimum_note_length: float = 80.0,
    minimum_frequency: Optional[float] = None,
    maximum_frequency: Optional[float] = None,
    clean_min_duration: float = 0.075,
    clean_min_amplitude: float = 0.055,
    merge_gap: float = 0.055,
    quantize: bool = True,
    quantize_subdivision: int = 4,
    quantize_strength: float = 0.65,
    density_limit: bool = True,
    density_window: float = 0.030,
    density_max_notes: int = 7,
    harmonic_cleanup: bool = True,
    keep_raw_midi: bool = False,
    verbose: bool = True,
) -> str:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"未找到音频文件: {audio_path}")
    if not is_audio_file(audio_path):
        raise ValueError(f"不支持的音频格式: {audio_path}")

    if output_midi_path is None:
        base, _ = os.path.splitext(audio_path)
        output_midi_path = f"{base}_clean.mid"
    output_midi_path = os.path.abspath(output_midi_path)

    os.makedirs(os.path.dirname(output_midi_path) or ".", exist_ok=True)
    start_time = time.time()

    if verbose:
        print()
        print("=" * 72)
        print("             MP3 -> Clean MIDI V3")
        print("=" * 72)
        print(f"输入: {audio_path}")

    # 1. 初始 BPM/Beat
    if bpm is None or bpm <= 0:
        if verbose:
            print("正在检测 BPM / Beat...")
        detected_bpm, beat_times = detect_tempo_and_beats(audio_path)
        initial_bpm = detected_bpm
    else:
        initial_bpm = float(bpm)
        _, beat_times = detect_tempo_and_beats(audio_path, default_bpm=initial_bpm)

    if verbose:
        print(f"初始 BPM: {initial_bpm:.2f} | Beat: {len(beat_times)}")

    # 2. Basic Pitch
    try:
        from basic_pitch.inference import predict
    except ImportError as exc:
        raise RuntimeError(
            "缺少 Basic Pitch，请安装 basic-pitch；同时确保 onnxruntime/librosa/pretty_midi 可用。"
        ) from exc

    if verbose:
        print("正在进行 Basic Pitch 转录...")

    model_output, raw_midi_data, raw_note_events = predict(
        audio_path,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=minimum_note_length,
        minimum_frequency=minimum_frequency,
        maximum_frequency=maximum_frequency,
        multiple_pitch_bends=False,
        # 初步 MIDI 阶段保留复音信息，避免过早抑制真实和弦。
        melodia_trick=False,
        midi_tempo=initial_bpm,
    )

    notes = convert_note_events(raw_note_events)
    raw_count = len(notes)

    if raw_count == 0:
        raise RuntimeError("Basic Pitch 没有检测到有效音符。")

    # 先用原始 note onset 判断 BPM 倍/半速，再做后续量化（用户显式指定 bpm 时完全尊重用户设定）
    if bpm is None or bpm <= 0:
        final_bpm = choose_tempo_candidate(initial_bpm, beat_times, notes)
        beat_times = adjust_beats_for_tempo_ratio(
            beat_times,
            initial_bpm,
            final_bpm,
        )
    else:
        final_bpm = initial_bpm

    # 3. 清洗流水线
    notes = filter_basic_notes(
        notes,
        min_duration=clean_min_duration,
        min_amplitude=clean_min_amplitude,
    )
    after_basic = len(notes)

    notes = adaptive_amplitude_filter(notes, percentile=8.0, max_threshold=0.12)
    after_amplitude = len(notes)

    notes = merge_same_pitch_notes(notes, max_gap=merge_gap)
    after_merge = len(notes)

    notes = clean_same_pitch_overlaps(notes, overlap_tolerance=0.035)
    after_overlap = len(notes)

    if harmonic_cleanup:
        notes = remove_harmonic_ghost_notes(notes)
    after_harmonic = len(notes)

    notes = remove_obvious_isolated_notes(notes)
    after_isolated = len(notes)

    if density_limit:
        notes = limit_extreme_note_density(
            notes,
            window=density_window,
            max_notes=density_max_notes,
        )
    after_density = len(notes)

    if not notes:
        raise RuntimeError(
            "清洗后没有剩余音符，请降低过滤强度（如 clean_min_amplitude/min_duration）。"
        )

    if quantize and len(beat_times) >= 2:
        notes = intelligent_quantize(
            notes,
            beat_times,
            subdivisions=quantize_subdivision,
            max_snap_ratio=0.22,
            strength=quantize_strength,
        )

    notes = final_note_cleanup(notes)
    final_count = len(notes)

    if final_count == 0:
        raise RuntimeError("最终 MIDI 没有可写入的音符。")

    # 4. 可选保存 raw
    if keep_raw_midi:
        base, _ = os.path.splitext(output_midi_path)
        raw_path = f"{base}_raw.mid"
        raw_midi_data.write(raw_path)

    # 5. 重建 clean MIDI
    clean_midi = build_clean_midi(notes, bpm=final_bpm)
    clean_midi.write(output_midi_path)

    elapsed = time.time() - start_time
    retention = final_count / raw_count if raw_count else 0.0

    if verbose:
        print()
        print("---------------- 清洗结果 ----------------")
        print(f"原始音符       : {raw_count}")
        print(f"基础过滤后     : {after_basic}")
        print(f"弱音过滤后     : {after_amplitude}")
        print(f"同音合并后     : {after_merge}")
        print(f"重叠修复后     : {after_overlap}")
        print(f"泛音清理后     : {after_harmonic}")
        print(f"孤立音清理后   : {after_isolated}")
        print(f"密度控制后     : {after_density}")
        print(f"最终 MIDI 音符 : {final_count}")
        print(f"最终 BPM       : {final_bpm:.2f}")
        print(f"保留率         : {retention * 100:.1f}%")
        if retention < 0.45:
            print("⚠ 清洗比例较高：建议检查这首歌是否属于复杂混音/鼓点很重的音乐。")
        print(f"输出           : {output_midi_path}")
        print(f"耗时           : {elapsed:.2f}s")
        print("=" * 72)
        print()

    return output_midi_path


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="MP3/WAV/FLAC -> 初步清洗 MIDI（供后续 15 键转换使用）"
    )

    parser.add_argument("input", help="输入音频")
    parser.add_argument("-o", "--output", default=None, help="输出 MIDI")
    parser.add_argument("--bpm", type=float, default=None, help="手动指定 BPM")

    parser.add_argument("--onset", type=float, default=0.55)
    parser.add_argument("--frame", type=float, default=0.30)
    parser.add_argument("--min-len", type=float, default=80.0)

    parser.add_argument("--clean-min-duration", type=float, default=0.075)
    parser.add_argument("--clean-min-amplitude", type=float, default=0.055)
    parser.add_argument("--merge-gap", type=float, default=0.055)

    parser.add_argument("--no-quantize", action="store_true")
    parser.add_argument("--quantize-subdivision", type=int, choices=[1, 2, 4, 8], default=4)
    parser.add_argument("--quantize-strength", type=float, default=0.65)

    parser.add_argument("--no-density-limit", action="store_true")
    parser.add_argument("--density-window", type=float, default=0.030)
    parser.add_argument("--density-max-notes", type=int, default=7)

    parser.add_argument("--no-harmonic-cleanup", action="store_true")
    parser.add_argument("--keep-raw", action="store_true")

    args = parser.parse_args()

    try:
        convert_audio_to_midi(
            args.input,
            output_midi_path=args.output,
            bpm=args.bpm,
            onset_threshold=args.onset,
            frame_threshold=args.frame,
            minimum_note_length=args.min_len,
            clean_min_duration=args.clean_min_duration,
            clean_min_amplitude=args.clean_min_amplitude,
            merge_gap=args.merge_gap,
            quantize=not args.no_quantize,
            quantize_subdivision=args.quantize_subdivision,
            quantize_strength=args.quantize_strength,
            density_limit=not args.no_density_limit,
            density_window=args.density_window,
            density_max_notes=max(1, args.density_max_notes),
            harmonic_cleanup=not args.no_harmonic_cleanup,
            keep_raw_midi=args.keep_raw,
            verbose=True,
        )
    except Exception as exc:
        print(f"转录失败: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
