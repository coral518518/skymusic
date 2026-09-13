import os
import glob
import struct
import math

MAJOR_PROF = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROF = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
SKY_PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]
KEY_NAMES = ["1", "2", "3", "4", "5", "6", "7", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "++1"]

SMART_MODES = [
    [0, 2, 4, 5, 7, 9, 11], # ionian
    [0, 2, 3, 5, 7, 9, 10], # dorian
    [0, 1, 3, 5, 7, 8, 10], # phrygian
    [0, 2, 4, 6, 7, 9, 11], # lydian
    [0, 2, 4, 5, 7, 9, 10], # mixolydian
    [0, 2, 3, 5, 7, 8, 10], # aeolian
    [0, 1, 3, 5, 6, 8, 10]  # locrian
]

def parse_midi_notes_and_keysig(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    ppq = division if division > 0 else 480
    offset = 14

    raw_notes = [] # list of (start_tick, length_ticks, note, vel, ch)
    active_notes = {} # (ch, note) -> (start_tick, vel)
    key_signatures = []

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
                if meta_type == 0x59 and l >= 2: # Key Signature
                    key = struct.unpack('>b', track_bytes[pos:pos+1])[0] # sf: -7..7
                    scale = track_bytes[pos+1] # 0 = major, 1 = minor
                    key_signatures.append((key, scale))
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
                    if ch != 9: # Skip percussion
                        if vel > 0:
                            if (ch, note) in active_notes:
                                s_tick, s_vel = active_notes[(ch, note)]
                                raw_notes.append((s_tick, max(1, cur_tick - s_tick), note, s_vel, ch))
                            active_notes[(ch, note)] = (cur_tick, vel)
                        else:
                            if (ch, note) in active_notes:
                                s_tick, s_vel = active_notes.pop((ch, note))
                                raw_notes.append((s_tick, max(1, cur_tick - s_tick), note, s_vel, ch))
                elif msg == 0x80:
                    note = track_bytes[pos]; vel = track_bytes[pos+1]; pos += 2
                    if ch != 9 and (ch, note) in active_notes:
                        s_tick, s_vel = active_notes.pop((ch, note))
                        raw_notes.append((s_tick, max(1, cur_tick - s_tick), note, s_vel, ch))
                elif msg in (0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    for (ch, note), (s_tick, s_vel) in active_notes.items():
        raw_notes.append((s_tick, ppq, note, s_vel, ch))

    raw_notes.sort(key=lambda x: x[0])
    return raw_notes, key_signatures

def mod12(val):
    return ((val % 12) + 12) % 12

def normalize_detected_key_offset(pitch_class):
    tonic = mod12(pitch_class)
    transposition = mod12(-tonic)
    return transposition - 12 if transposition >= 6 else transposition

def auto_midi_player_detect_key(raw_notes, key_signatures):
    # 1. Try Key Signature
    if key_signatures:
        key, scale = key_signatures[0]
        is_minor = (scale == 1)
        tonic_pitch_class = mod12((9 if is_minor else 0) + key * 7)
        return normalize_detected_key_offset(tonic_pitch_class), "KeySignature"

    # 2. Pitch Class Profile
    histogram = [0.0] * 12
    for _, length, note, _, _ in raw_notes:
        pc = mod12(note)
        histogram[pc] += max(1, length)

    best_score = -float('inf')
    best_tonic = 0
    for tonic in range(12):
        maj_score = 0.0
        min_score = 0.0
        for interval in range(12):
            weight = histogram[mod12(tonic + interval)]
            maj_score += weight * MAJOR_PROF[interval]
            min_score += weight * MINOR_PROF[interval]
        if maj_score > best_score:
            best_score = maj_score
            best_tonic = tonic
        if min_score > best_score:
            best_score = min_score
            best_tonic = tonic

    return normalize_detected_key_offset(best_tonic), "PitchClassProfile"

def auto_midi_player_smart_transpose(note_id):
    note_set = set(SKY_PITCHES)
    if note_id in note_set:
        return note_id

    min_note = 60
    max_note = 84

    folded = note_id
    while folded < min_note: folded += 12
    while folded > max_note: folded -= 12
    if folded in note_set:
        return folded

    # Best scale detection
    histogram = [0.0] * 12
    for n in SKY_PITCHES:
        pc = mod12(n)
        w = 1.0 / (1.0 + abs(n - folded))
        histogram[pc] += w

    best_score = -float('inf')
    best_tonic = 0
    best_mode = 0
    for tonic in range(12):
        for m_idx, mode in enumerate(SMART_MODES):
            sc = sum(histogram[(tonic + itv) % 12] for itv in mode)
            if sc > best_score:
                best_score = sc
                best_tonic = tonic
                best_mode = m_idx

    scale_pcs = set((best_tonic + itv) % 12 for itv in SMART_MODES[best_mode])
    candidates = [n for n in SKY_PITCHES if mod12(n) in scale_pcs]
    if not candidates:
        candidates = list(SKY_PITCHES)

    best = candidates[0]
    best_sc = float('inf')
    for c in candidates:
        target_dist = abs(c - folded)
        oct_dist = abs((c // 12) - (folded // 12))
        sc = target_dist + (oct_dist * 0.15)
        if sc < best_sc:
            best_sc = sc
            best = c

    return best

for f in sorted(glob.glob("e:/work/skymusic/midi_downloads/*.mid")):
    notes, ksig = parse_midi_notes_and_keysig(f)
    amp_shift, src = auto_midi_player_detect_key(notes, ksig)
    print("="*50)
    print(f"File: {os.path.basename(f)}")
    print(f"AutoMidiPlayer Key Offset: {amp_shift:+d} (from {src}) | Total Notes: {len(notes)}")
    
    # Test playable count under AutoMidiPlayer
    mapped_keys = []
    for s_tick, _, note, _, _ in notes:
        n_id = note + amp_shift
        transposed = auto_midi_player_smart_transpose(n_id)
        if transposed in SKY_PITCHES:
            k_idx = SKY_PITCHES.index(transposed)
            mapped_keys.append((s_tick, k_idx))

    key_counts = [0] * 15
    for _, k in mapped_keys: key_counts[k] += 1
    print(f"Key Distribution (0..14): {key_counts}")
    snippet = " ".join([KEY_NAMES[k] for _, k in mapped_keys[:25]])
    print(f"Melody Snippet: {snippet}")
