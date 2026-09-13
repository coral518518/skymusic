import os
import glob
import struct
import math

MAJOR_PROF = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROF = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
SKY_PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]
KEY_NAMES = ["1", "2", "3", "4", "5", "6", "7", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "++1"]

def pearson(x, y):
    mean_x = sum(x) / 12.0
    mean_y = sum(y) / 12.0
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(12))
    den_x = sum((x[i] - mean_x)**2 for i in range(12))
    den_y = sum((y[i] - mean_y)**2 for i in range(12))
    den = (den_x * den_y) ** 0.5
    return num / den if den != 0 else 0

def parse_full_midi(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    ppq = division if division > 0 else 480
    offset = 14

    raw_notes = []
    tempo_changes = [(0, 500000)]
    for t in range(tracks):
        if offset + 8 > len(data): break
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]; offset += 8
        track_bytes = data[offset:offset+chunk_len]; offset += chunk_len
        pos = 0; cur_tick = 0; running_status = 0
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
                    if vel > 0 and ch != 9:
                        raw_notes.append((cur_tick, note, vel))
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    tempo_changes.sort(key=lambda x: x[0])
    def tick_to_ms(tick):
        cur_tick = 0; cur_us = tempo_changes[0][1]; elapsed = 0
        for ch_tick, us in tempo_changes:
            if tick <= ch_tick: break
            elapsed += (ch_tick - cur_tick) * cur_us / (ppq * 1000.0)
            cur_tick = ch_tick; cur_us = us
        elapsed += (tick - cur_tick) * cur_us / (ppq * 1000.0)
        return int(round(elapsed))

    # Krumhansl
    counts = [0] * 12
    for _, p, _ in raw_notes: counts[p % 12] += 1
    best_score = -999; best_shift = 0
    for tonic in range(12):
        rot = [counts[(tonic + i) % 12] for i in range(12)]
        sMaj = pearson(rot, MAJOR_PROF); sMin = pearson(rot, MINOR_PROF)
        if sMaj > best_score:
            best_score = sMaj; s = (12 - tonic) % 12
            if s > 6: s -= 12
            best_shift = s
        if sMin > best_score:
            best_score = sMin; s = (9 - tonic) % 12
            if s > 6: s -= 12
            best_shift = s

    # Base octave
    transposed = [p + best_shift for _, p, _ in raw_notes]
    best_oct = 0; max_in = -1
    for oct_s in [-24, -12, 0, 12, 24]:
        cnt = sum(1 for p in transposed if 60 <= p + oct_s <= 84)
        if cnt > max_in: max_in = cnt; best_oct = oct_s

    time_map = {}
    for tick, pitch, _ in raw_notes:
        ms = tick_to_ms(tick)
        p = pitch + best_shift + best_oct
        while p < 60: p += 12
        while p > 84: p -= 12
        best_k = 0; min_d = 999
        for i, target in enumerate(SKY_PITCHES):
            d = abs(p - target)
            if d < min_d: min_d = d; best_k = i;
            if d == 0: break
        q_time = int(round(ms / 30.0) * 30)
        if q_time not in time_map: time_map[q_time] = []
        if best_k not in time_map[q_time]: time_map[q_time].append(best_k)

    notes = []
    for t in sorted(time_map.keys()):
        raw_k = sorted(list(set(time_map[t])))
        if len(raw_k) > 4:
            k = [raw_k[0], raw_k[-1]]
            mid = raw_k[1:-1]
            if len(mid) == 1: k.append(mid[0])
            elif len(mid) >= 2: k.extend([mid[0], mid[-1]])
            raw_k = sorted(list(set(k)))
        notes.append((t, raw_k))

    return best_shift, best_oct, notes

for f in sorted(glob.glob("e:/work/skymusic/midi_downloads/*.mid")):
    s, o, notes = parse_full_midi(f)
    print(f"\n==========================================")
    print(f"File: {os.path.basename(f)}")
    print(f"Detected Shift: {s:+d}, Base Octave: {o:+d}, Total Chords: {len(notes)}")
    key_counts = [0] * 15
    for t, keys in notes:
        for k in keys: key_counts[k] += 1
    print(f"Key Distribution (0..14): {key_counts}")
    # Sample snippet of melody:
    snippet = " ".join([KEY_NAMES[k[-1]] for _, k in notes[:25]])
    print(f"Top Voice Melody Snippet: {snippet}")
