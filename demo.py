import mido
from collections import Counter
import math

# 光遇 15 键对应的标准 MIDI 音高（C4=60 体系：低音1到高音1'）
# 实际覆盖范围为 C3(48) 到 C5(72) 的自然大调音阶
SKY_KEYS = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72]
NATURAL_NOTES = {0, 2, 4, 5, 7, 9, 11}  # C 大调音级 (C, D, E, F, G, A, B)

def parse_midi_notes(mid):
    """提取 MIDI 中所有非打击乐音符，解析绝对时间与轨道"""
    tracks_notes = []
    for i, track in enumerate(mid.tracks):
        current_time = 0
        active_notes = {}
        notes = []
        is_drum = False
        
        for msg in track:
            current_time += msg.time
            if msg.type in ['note_on', 'note_off']:
                # 过滤第 10 通道（标准打击乐通道 channel 9）
                if msg.channel == 9:
                    is_drum = True
                    break
                velocity = msg.velocity if msg.type == 'note_on' else 0
                pitch = msg.note
                
                if velocity > 0:
                    active_notes[pitch] = current_time
                elif pitch in active_notes:
                    start_time = active_notes.pop(pitch)
                    duration = current_time - start_time
                    notes.append({'pitch': pitch, 'start': start_time, 'dur': duration, 'track': i})
        
        if not is_drum and notes:
            tracks_notes.append(notes)
    return tracks_notes

def find_best_transpose(all_notes):
    """全局移调优化：遍历 -6 到 +6 半音，找出落入自然白键最多的移调量"""
    best_shift = 0
    max_score = -float('inf')
    
    for shift in range(-6, 6):
        score = 0
        for n in all_notes:
            pitch_class = (n['pitch'] + shift) % 12
            if pitch_class in NATURAL_NOTES:
                score += 1  # 命中白键加分
            else:
                score -= 3  # 命中了黑键（半音）重罚
        if score > max_score:
            max_score = score
            best_shift = shift
    return best_shift

def score_track_for_melody(notes):
    """
    旋律识别启发式：
    主旋律特征：音高相对较高、极少同时按下多键（多音率低）、音长均匀
    """
    if not notes:
        return -1
    avg_pitch = sum(n['pitch'] for n in notes) / len(notes)
    
    # 检测重叠音（和弦密集度）
    time_points = [n['start'] for n in notes]
    overlap_count = len(time_points) - len(set(time_points))
    polyphony_rate = overlap_count / len(notes)
    
    # 评分公式：音高权重 + 单音纯净度权重
    score = (avg_pitch * 0.6) - (polyphony_rate * 50)
    return score

def fit_to_sky_range(pitch, target_register="melody"):
    """
    将音高折叠并强制吸附到光遇 15 键
    """
    # 1. 强制消除非自然半音（就近吸附到自然音）
    pitch_class = pitch % 12
    if pitch_class not in NATURAL_NOTES:
        # 半音就近修正
        pitch = pitch - 1 if (pitch_class - 1) % 12 in NATURAL_NOTES else pitch + 1
        
    # 2. 按功能区折叠八度
    # 旋律区优先保留在中高音区 (60~72)，伴奏区保留在低音区 (48~59)
    if target_register == "melody":
        while pitch < 57:
            pitch += 12
        while pitch > 72:
            pitch -= 12
    else:
        while pitch < 48:
            pitch += 12
        while pitch > 60:
            pitch -= 12
            
    # 3. 兜底夹断到 15 键最接近的值
    return min(SKY_KEYS, key=lambda x: abs(x - pitch))

def process_midi_to_sky(input_file, output_file):
    mid = mido.MidiFile(input_file)
    tracks_notes = parse_midi_notes(mid)
    
    if not tracks_notes:
        print("未检测到有效音轨！")
        return

    # 合并所有音符寻找全局最佳调性
    flat_notes = [n for track in tracks_notes for n in track]
    best_shift = find_best_transpose(flat_notes)
    print(f"[1/4] 自动移调优化完成：最佳半音偏移为 {best_shift:+d}")

    # 识别出旋律轨道
    track_scores = [(i, score_track_for_melody(t)) for i, t in enumerate(tracks_notes)]
    track_scores.sort(key=lambda x: x[1], reverse=True)
    melody_idx = track_scores[0][0]
    print(f"[2/4] 主旋律轨道定位完成：Track #{melody_idx}")

    # 分流提取：旋律轨 vs 伴奏轨
    melody_notes = tracks_notes[melody_idx]
    accompaniment_notes = []
    for i, t in enumerate(tracks_notes):
        if i != melody_idx:
            accompaniment_notes.extend(t)

    # 处理旋律音（移调 + 音域拟合）
    processed_events = []
    for n in melody_notes:
        shifted = n['pitch'] + best_shift
        sky_pitch = fit_to_sky_range(shifted, target_register="melody")
        processed_events.append({'pitch': sky_pitch, 'start': n['start'], 'dur': n['dur'], 'is_melody': True})

    # 处理伴奏音：强行抽稀（每小节/拍只取最低音根音）
    accompaniment_notes.sort(key=lambda x: x['start'])
    sparse_accompaniment = []
    last_acc_time = -9999
    min_interval = mid.ticks_per_beat // 2  # 伴奏至少间隔半拍，避免砸琴

    for n in accompaniment_notes:
        if n['start'] - last_acc_time >= min_interval:
            shifted = n['pitch'] + best_shift
            sky_pitch = fit_to_sky_range(shifted, target_register="acc")
            sparse_accompaniment.append({'pitch': sky_pitch, 'start': n['start'], 'dur': n['dur'], 'is_melody': False})
            last_acc_time = n['start']

    print(f"[3/4] 伴奏和弦稀疏化完成：过滤掉密集内声部")

    # 合并并按时间排序
    final_notes = processed_events + sparse_accompaniment
    final_notes.sort(key=lambda x: x['start'])

    # 4. 重新组装为单轨干净 MIDI
    out_mid = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat)
    out_track = mido.MidiTrack()
    out_mid.tracks.append(out_track)

    events = []
    for n in final_notes:
        events.append((n['start'], 'note_on', n['pitch'], 90 if n['is_melody'] else 60))
        events.append((n['start'] + n['dur'], 'note_off', n['pitch'], 0))
    events.sort(key=lambda x: x[0])

    current_tick = 0
    for tick, event_type, pitch, vel in events:
        delta = max(0, tick - current_tick)
        out_track.append(mido.Message(event_type, note=pitch, velocity=vel, time=delta))
        current_tick = tick

    out_mid.save(output_file)
    print(f"[4/4] 导出成功 -> {output_file}，可直接导入练习软件！")

if __name__ == "__main__":
    # 替换你的输入文件名
    process_midi_to_sky("input.mid", "sky_converted.mid")