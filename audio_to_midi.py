#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""音频转 MIDI (Audio to MIDI) 模块

基于 Spotify Basic Pitch (ONNX Runtime 引擎) 与 Librosa，
专为多音符钢琴、复调伴奏与器乐设计的高精度音频转录工具。
"""

import argparse
import logging
import os
import sys
import time
import warnings
from typing import Optional, Tuple

# 屏蔽不必要的第三方依赖缺失警告
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

# 确保控制台支持 UTF-8 打印
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}


def is_audio_file(filepath: str) -> bool:
    """检查文件是否为支持的音频格式"""
    if not filepath:
        return False
    _, ext = os.path.splitext(filepath.lower())
    return ext in AUDIO_EXTENSIONS


def detect_tempo(audio_path: str, default_bpm: float = 120.0) -> float:
    """利用 librosa.beat.beat_track 自动检测音频速度 (BPM)"""
    try:
        import librosa
        import numpy as np

        # 只需加载部分典型音频即可快速精准测速
        y, sr = librosa.load(audio_path, sr=22050, duration=90.0)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        detected = float(np.atleast_1d(tempo)[0])
        if 40.0 <= detected <= 240.0:
            return round(detected, 2)
    except Exception:
        pass
    return default_bpm


def convert_audio_to_midi(
    audio_path: str,
    output_midi_path: Optional[str] = None,
    bpm: Optional[float] = None,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    minimum_note_length: float = 58.0,
    minimum_frequency: Optional[float] = None,
    maximum_frequency: Optional[float] = None,
    verbose: bool = True,
) -> str:
    """将音频（MP3/WAV/FLAC等）转录为 MIDI 文件。

    Args:
        audio_path: 输入音频文件路径
        output_midi_path: 输出 MIDI 文件路径（如未指定，默认与音频同名同目录，扩展名为 .mid）
        bpm: 手动指定速度（如未指定，自动检测）
        onset_threshold: 起音阈值 (0.0~1.0)，越小越灵敏，默认 0.5
        frame_threshold: 持续音帧能量阈值 (0.0~1.0)，默认 0.3
        minimum_note_length: 最短音符长度（毫秒），过滤超短杂音，默认 58.0ms
        minimum_frequency: 最低频率（Hz），如钢琴最低音 A0 约为 27.5Hz
        maximum_frequency: 最高频率（Hz），如钢琴最高音 C8 约为 4186Hz
        verbose: 是否打印详细转换进度

    Returns:
        output_midi_path: 生成的 MIDI 文件绝对路径
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"未找到音频文件: {audio_path}")

    if output_midi_path is None:
        base, _ = os.path.splitext(audio_path)
        output_midi_path = f"{base}.mid"

    if verbose:
        print()
        print("=" * 60)
        print("       音频转 MIDI (Audio to MIDI)")
        print("=" * 60)
        print(f"音频输入: {audio_path}")

    start_time = time.time()

    # 1. 速度 (BPM) 检测
    if bpm is None or bpm <= 0:
        if verbose:
            print("正在检测歌曲速度 (BPM)...", end="", flush=True)
        detected_bpm = detect_tempo(audio_path, default_bpm=120.0)
        final_bpm = detected_bpm
        if verbose:
            print(f" 速度识别: {final_bpm:.2f} BPM")
    else:
        final_bpm = float(bpm)
        if verbose:
            print(f"设定速度: {final_bpm:.2f} BPM")

    # 2. 导入转录引擎
    if verbose:
        print("加载转录引擎 (Basic Pitch ONNX)...", end="", flush=True)
    try:
        from basic_pitch.inference import predict
    except ImportError as e:
        raise RuntimeError(
            f"缺少转录所需依赖库: {e}。\n"
            "请确保已安装 onnxruntime, basic-pitch, librosa, soundfile"
        )
    if verbose:
        print(" 完成")

    # 3. 执行音频音符预测
    if verbose:
        print("正在分析并提取多音轨音符 (通常需 10~30 秒)...", flush=True)

    model_output, midi_data, note_events = predict(
        audio_path,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=minimum_note_length,
        minimum_frequency=minimum_frequency,
        maximum_frequency=maximum_frequency,
        multiple_pitch_bends=False,
        melodia_trick=True,
        midi_tempo=final_bpm,
    )

    # 4. 写入 MIDI 文件
    midi_data.write(output_midi_path)
    elapsed = time.time() - start_time

    note_count = len(note_events) if note_events else 0

    if verbose:
        print(f"转录完成! 提取到音符: {note_count} 个, 耗时: {elapsed:.2f} 秒")
        print(f"MIDI 输出: {output_midi_path}")
        print("=" * 60)
        print()

    return output_midi_path


def main():
    parser = argparse.ArgumentParser(description="音频转 MIDI (MP3/WAV/FLAC -> MIDI)")
    parser.add_argument("input", help="输入音频文件 (.mp3, .wav, .flac 等)")
    parser.add_argument("-o", "--output", default=None, help="输出 MIDI 文件路径")
    parser.add_argument("--bpm", type=float, default=None, help="指定 BPM (默认自动检测)")
    parser.add_argument("--onset", type=float, default=0.5, help="起音阈值 (默认 0.5)")
    parser.add_argument("--frame", type=float, default=0.3, help="持续帧阈值 (默认 0.3)")
    parser.add_argument("--min-len", type=float, default=58.0, help="最短音符毫秒 (默认 58.0)")

    args = parser.parse_args()

    try:
        convert_audio_to_midi(
            args.input,
            output_midi_path=args.output,
            bpm=args.bpm,
            onset_threshold=args.onset,
            frame_threshold=args.frame,
            minimum_note_length=args.min_len,
        )
    except Exception as e:
        print(f"转录失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
