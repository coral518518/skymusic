import os
import glob
import struct
import math

SKY_KEYS = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72]
NATURAL_NOTES = {0, 2, 4, 5, 7, 9, 11}
KEY_NAMES = ["1", "2", "3", "4", "5", "6", "7", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "++1"]

def parse_full_midi(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    ppq = division if division > 0 else 480
    offset = 14

    tracks_notes = []
    tempo_changes = [(0, 500000)]
    for t in range(tracks):
        if offset + 8 > len(data): break
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]; offset += 8
        track_bytes = data[offset:offset+chunk_len]; offset += chunk_len
        pos = 0; cur_tick = 0; running_status = 0
        track_notes = []
        active_notes = {}
        while pos < len(track_bytes):
            delta = 0
            while True:
                if pos >= len(track_bytes): break
                b = track_bytes[pos]; pos += 1; delta = (delta<<7)|(b&0x7F)
                if not (b&0x80): break
            cur_tick += delta
            if pos >= len(track_bytes): break
            status = track_bytes[pos]
            if status < 0x80:
                if running_status == 0: break
                status = running_status
            else:
                pos += 1
                running_status = status if status < 0xF0 else 0
            if status == 0xFF:
                meta_type = track_bytes[pos]; pos += 1
                l = 0
                while True:
                    b = track_bytes[pos]; pos += 1; l = (l<<7)|(b&0x7F)
                    if not (b&0x80): break
                if meta_type == 0x51 and l >= 3:
                    us = (track_bytes[pos]<<16)|(track_bytes[pos+1]<<8)|track_bytes[pos+2]
                    tempo_changes.append((cur_tick, us))
                pos += l
            elif status in (0xF0, 0xF7):
                l = 0
                while True:
                    b = track_bytes[pos]; pos += 1; l = (l<<7)|(b&0x7F)
                    if not (b&0x80): break
                pos += l
            else:
                msg = status & 0xF0; ch = status & 0x0F
                if msg == 0x90:
                    note = track_bytes[pos]; vel = track_bytes[pos+1]; pos += 2
                    if ch != 9:
                        k = (ch, note)
                        if vel > 0:
                            if k in active_notes:
                                st = active_notes[k]
                                track_notes.append({'pitch': note, 'startTick': st, 'dur': max(1, cur_tick - st), 'ch': ch, 'trk': t})
                            active_notes[k] = cur_tick
                        else:
                            if k in active_notes:
                                st = active_notes.pop(k)
                                track_notes.append({'pitch': note, 'startTick': st, 'dur': max(1, cur_tick - st), 'ch': ch, 'trk': t})
                elif msg == 0x80:
                    note = track_bytes[pos]; pos += 2
                    if ch != 9:
                        k = (ch, note)
                        if k in active_notes:
                            st = active_notes.pop(k)
                            track_notes.append({'pitch': note, 'startTick': st, 'dur': max(1, cur_tick - st), 'ch': ch, 'trk': t})
                elif msg in (0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

        for (ch, note), st in active_notes.items():
            track_notes.append({'pitch': note, 'startTick': st, 'dur': ppq, 'ch': ch, 'trk': t})

        if track_notes:
            tracks_notes.append(track_notes)

    if not tracks_notes:
        return 0, []

    tempo_changes.sort(key=lambda x: x[0])
    def tick_to_ms(tick):
        cur_tick = 0; cur_us = tempo_changes[0][1]; elapsed = 0
        for ch_tick, us in tempo_changes:
            if tick <= ch_tick: break
            elapsed += (ch_tick - cur_tick) * cur_us / (ppq * 1000.0)
            cur_tick = ch_tick; cur_us = us
        elapsed += (tick - cur_tick) * cur_us / (ppq * 1000.0)
        return int(round(elapsed))

    all_flat = [n for trk in tracks_notes for n in trk]

    # 1. 全局最佳移调优化
    best_shift = 0
    max_score = -float('inf')
    for s in range(-6, 7):
        sc = 0
        for n in all_flat:
            pc = ((n['pitch'] + s) % 12 + 12) % 12
            sc += 1 if pc in NATURAL_NOTES else -3
        if sc > max_score or (sc == max_score and abs(s) < abs(best_shift)):
            max_score = sc
            best_shift = s

    # 2. 启发式主旋律识别
    def score_track_for_melody(notes):
        if not notes: return -1.0
        avg_p = sum(n['pitch'] for n in notes) / len(notes)
        time_points = [n['startTick'] for n in notes]
        overlap_count = len(time_points) - len(set(time_points))
        polyphony_rate = overlap_count / len(notes)
        note_bonus = min(len(notes), 400) * 0.02
        return (avg_p * 0.6) - (polyphony_rate * 50.0) + note_bonus

    melody_notes = []
    accompaniment_notes = []

    if len(tracks_notes) > 1:
        scored = [(i, score_track_for_melody(t)) for i, t in enumerate(tracks_notes)]
        scored.sort(key=lambda x: x[1], reverse=True)
        mel_idx = scored[0][0]
        for i in range(len(tracks_notes)):
            if i == mel_idx:
                melody_notes.extend(tracks_notes[i])
            else:
                accompaniment_notes.extend(tracks_notes[i])
    else:
        single_trk = tracks_notes[0]
        chs = list(set(n['ch'] for n in single_trk))
        if len(chs) > 1:
            ch_groups = {}
            for n in single_trk:
                ch_groups.setdefault(n['ch'], []).append(n)
            scored_chs = [(ch, score_track_for_melody(notes)) for ch, notes in ch_groups.items()]
            scored_chs.sort(key=lambda x: x[1], reverse=True)
            mel_ch = scored_chs[0][0]
            for ch, notes in ch_groups.items():
                if ch == mel_ch:
                    melody_notes.extend(notes)
                else:
                    accompaniment_notes.extend(notes)
        else:
            by_start = {}
            for n in single_trk:
                by_start.setdefault(n['startTick'], []).append(n)
            for st, grp in by_start.items():
                grp.sort(key=lambda x: x['pitch'], reverse=True)
                melody_notes.append(grp[0])
                if len(grp) > 1:
                    accompaniment_notes.extend(grp[1:])

    # 3. 折叠到光遇 15 键
    def fit_to_sky_key(pitch, is_melody):
        p = pitch
        pc = ((p % 12) + 12) % 12
        if pc not in NATURAL_NOTES:
            down_pc = ((pc - 1) % 12 + 12) % 12
            p = p - 1 if down_pc in NATURAL_NOTES else p + 1
        if is_melody:
            while p < 57: p += 12
            while p > 72: p -= 12
        else:
            while p < 48: p += 12
            while p > 60: p -= 12
        best_key = 0
        min_diff = 9999
        for i, sk in enumerate(SKY_KEYS):
            d = abs(p - sk)
            if d < min_diff:
                min_diff = d
                best_key = i
                if d == 0: break
        return best_key

    # 4. 处理旋律音与抽稀伴奏音
    processed = []
    for n in melody_notes:
        shifted = n['pitch'] + best_shift
        k = fit_to_sky_key(shifted, is_melody=True)
        ms = tick_to_ms(n['startTick'])
        processed.append((ms, k, True))

    accompaniment_notes.sort(key=lambda x: (x['startTick'], x['pitch']))
    min_interval_ticks = max(1, ppq // 2)
    last_acc_tick = -999999
    for n in accompaniment_notes:
        if n['startTick'] - last_acc_tick >= min_interval_ticks:
            shifted = n['pitch'] + best_shift
            k = fit_to_sky_key(shifted, is_melody=False)
            ms = tick_to_ms(n['startTick'])
            processed.append((ms, k, False))
            last_acc_tick = n['startTick']

    processed.sort(key=lambda x: x[0])

    # 5. 25ms 时间窗聚合
    time_map = {}
    for ms, k, is_mel in processed:
        q_time = int(round(ms / 25.0) * 25)
        time_map.setdefault(q_time, [])
        if k not in time_map[q_time]:
            time_map[q_time].append(k)

    notes = []
    for t in sorted(time_map.keys()):
        raw_k = sorted(list(set(time_map[t])))
        if len(raw_k) > 3:
            raw_k = sorted(list(set([raw_k[0], raw_k[len(raw_k)//2], raw_k[-1]])))
        notes.append((t, raw_k))

    return best_shift, notes

all_files = sorted(glob.glob("e:/work/skymusic/midi_downloads/*.mid") + 
                   glob.glob("e:/work/skymusic/*.mid") + 
                   glob.glob("e:/work/skymusic/app/src/main/assets/songs/*.mid"))

for f in all_files:
    s, notes = parse_full_midi(f)
    print(f"\n==========================================")
    print(f"File: {os.path.basename(f)}")
    print(f"Detected Shift: {s:+d}, Total Chords: {len(notes)}")
    key_counts = [0] * 15
    for t, keys in notes:
        for k in keys: key_counts[k] += 1
    print(f"Key Distribution (0..14): {key_counts}")
    snippet = " ".join([KEY_NAMES[k[-1]] for _, k in notes[:25]])
    print(f"Top Voice Melody Snippet: {snippet}")
