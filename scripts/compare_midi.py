import os
import struct

# Sky key to Jianpu (numbered notation):
# 0..6: 1 2 3 4 5 6 7 (low)
# 7..13: 1+ 2+ 3+ 4+ 5+ 6+ 7+ (mid)
# 14: 1++ (high)
KEY_NAMES = [
    "1", "2", "3", "4", "5", "6", "7",
    "+1", "+2", "+3", "+4", "+5", "+6", "+7",
    "++1"
]

SKY_PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]
DIATONIC = {0, 2, 4, 5, 7, 9, 11}

def parse_with_old_logic(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    ppq = division if division > 0 else 480
    offset = 14

    raw_notes = []
    tempo_changes = [(0, 500000)]
    for t in range(tracks):
        if offset + 8 > len(data): break
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]
        offset += 8
        track_bytes = data[offset:offset+chunk_len]
        offset += chunk_len
        pos = 0; cur_tick = 0; running_status = 0
        while pos < len(track_bytes):
            delta = 0
            while True:
                if pos >= len(track_bytes): break
                b = track_bytes[pos]; pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if not (b & 0x80): break
            cur_tick += delta
            if pos >= len(track_bytes): break
            status = track_bytes[pos]
            if status < 0x80: status = running_status
            else:
                pos += 1
                # BUG in old code: runningStatus = status unconditionally!
                running_status = status
            if status == 0xFF:
                pos += 1
                l = 0
                while True:
                    b = track_bytes[pos]; pos += 1; l = (l<<7)|(b&0x7F)
                    if not (b&0x80): break
                if pos + 3 <= len(track_bytes) and track_bytes[pos-2] == 0x51: # tempo
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
                msg = status & 0xF0
                if msg == 0x90:
                    note = track_bytes[pos]; vel = track_bytes[pos+1]; pos += 2
                    if vel > 0: raw_notes.append((cur_tick, note))
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    # Old transpose:
    best_shift = 0; max_h = -1
    for s in range(-6, 7):
        h = sum(1 for _, p in raw_notes if ((p + s)%12) in DIATONIC)
        if h > max_h: max_h = h; best_shift = s

    # Old octave shift:
    sorted_p = sorted([p + best_shift for _, p in raw_notes])
    median = sorted_p[len(sorted_p)//2] if sorted_p else 72
    oct_shift = int(round((72 - median) / 12.0) * 12)

    # Old key mapping:
    def old_map(p):
        final_p = p + best_shift + oct_shift
        if final_p <= 60: return 0
        if final_p >= 84: return 14
        best_k = 0; min_d = 999
        for i, target in enumerate(SKY_PITCHES):
            d = abs(final_p - target)
            if d < min_d: min_d = d; best_k = i
        return best_k

    events = []
    for tick, p in raw_notes[:40]:
        k = old_map(p)
        events.append(KEY_NAMES[k])
    return best_shift, oct_shift, events

def parse_with_fixed_logic(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    ppq = division if division > 0 else 480
    offset = 14

    raw_notes = []
    tempo_changes = [(0, 500000)]
    for t in range(tracks):
        if offset + 8 > len(data): break
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]
        offset += 8
        track_bytes = data[offset:offset+chunk_len]
        offset += chunk_len
        pos = 0; cur_tick = 0; running_status = 0
        while pos < len(track_bytes):
            delta = 0
            while True:
                if pos >= len(track_bytes): break
                b = track_bytes[pos]; pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if not (b & 0x80): break
            cur_tick += delta
            if pos >= len(track_bytes): break
            status = track_bytes[pos]
            if status < 0x80: status = running_status
            else:
                pos += 1
                # FIXED: running status only set for channel messages < 0xF0
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
                msg = status & 0xF0
                ch = status & 0x0F
                if msg == 0x90:
                    note = track_bytes[pos]; vel = track_bytes[pos+1]; pos += 2
                    # FIXED: Exclude drum channel 9
                    if vel > 0 and ch != 9:
                        raw_notes.append((cur_tick, note, vel))
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    # Fixed transpose:
    best_shift = 0; max_h = -1
    for s in range(-6, 7):
        h = sum(1 for _, p, _ in raw_notes if ((p + s)%12) in DIATONIC)
        if h > max_h: max_h = h; best_shift = s

    # Fixed octave folding:
    def fixed_map(p):
        transposed = p + best_shift
        # Octave fold to 60..84
        while transposed < 60: transposed += 12
        while transposed > 84: transposed -= 12
        best_k = 0; min_d = 999
        for i, target in enumerate(SKY_PITCHES):
            d = abs(transposed - target)
            if d < min_d: min_d = d; best_k = i
        return best_k

    events = []
    for tick, p, _ in raw_notes[:40]:
        k = fixed_map(p)
        events.append(KEY_NAMES[k])
    return best_shift, 0, events

for name in ["鸳鸯戏_259281.mid", "如果可以-韋禮安_259259.mid", "反乌托邦_259276.mid"]:
    p = f"e:/work/skymusic/midi_downloads/{name}"
    s1, o1, e1 = parse_with_old_logic(p)
    s2, o2, e2 = parse_with_fixed_logic(p)
    print(f"\n==================== {name} ====================")
    print(f"OLD METHOD  (shift={s1}, oct={o1}):\n{' '.join(e1[:30])}")
    print(f"FIXED METHOD(shift={s2}):\n{' '.join(e2[:30])}")
