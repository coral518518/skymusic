import os

SKY_KEY_PITCHES = [
    60, 62, 64, 65, 67, 69, 71,
    72, 74, 76, 77, 79, 81, 83,
    84
]

def midi_pitch_to_sky_key_current(pitch):
    if pitch <= SKY_KEY_PITCHES[0]: return 0
    if pitch >= SKY_KEY_PITCHES[-1]: return 14
    best_key = 0
    min_diff = 999
    for i, p in enumerate(SKY_KEY_PITCHES):
        diff = abs(pitch - p)
        if diff < min_diff:
            min_diff = diff
            best_key = i
    return best_key

# Now let's test what happens with octave folding:
def midi_pitch_to_sky_key_octave_folded(pitch):
    # pitch is already transposed to C major
    # Fold octave until it is within [60, 84]
    p = pitch
    while p < 60:
        p += 12
    while p > 84:
        p -= 12
    
    # Now p is guaranteed between 60 and 84
    # Map to diatonic scale in C
    best_key = 0
    min_diff = 999
    for i, target in enumerate(SKY_KEY_PITCHES):
        diff = abs(p - target)
        if diff < min_diff:
            min_diff = diff
            best_key = i
    return best_key

def test_key_distribution(filepath):
    import struct
    with open(filepath, 'rb') as f:
        data = f.read()

    header_len = struct.unpack('>I', data[4:8])[0]
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    offset = 8 + header_len

    notes = []
    for t in range(tracks):
        if offset + 8 > len(data): break
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]
        offset += 8
        track_bytes = data[offset:offset+chunk_len]
        offset += chunk_len
        pos = 0
        cur_tick = 0
        running_status = 0
        while pos < len(track_bytes):
            delta = 0
            while True:
                if pos >= len(track_bytes): break
                b = track_bytes[pos]
                pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if not (b & 0x80): break
            cur_tick += delta
            if pos >= len(track_bytes): break
            status = track_bytes[pos]
            if status < 0x80:
                status = running_status
            else:
                pos += 1
                running_status = status if status < 0xF0 else 0
            if status == 0xFF:
                if pos >= len(track_bytes): break
                meta_type = track_bytes[pos]; pos += 1
                meta_len = 0
                while True:
                    if pos >= len(track_bytes): break
                    b = track_bytes[pos]; pos += 1
                    meta_len = (meta_len << 7) | (b & 0x7F)
                    if not (b & 0x80): break
                pos += meta_len
            elif status in (0xF0, 0xF7):
                sysex_len = 0
                while True:
                    if pos >= len(track_bytes): break
                    b = track_bytes[pos]; pos += 1
                    sysex_len = (sysex_len << 7) | (b & 0x7F)
                    if not (b & 0x80): break
                pos += sysex_len
            else:
                msg = status & 0xF0
                ch = status & 0x0F
                if msg == 0x90:
                    note = track_bytes[pos]
                    vel = track_bytes[pos+1]
                    pos += 2
                    if vel > 0 and ch != 9:
                        notes.append(note)
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    DIATONIC = {0, 2, 4, 5, 7, 9, 11}
    best_shift = 0
    max_h = -1
    for s in range(-6, 7):
        h = sum(1 for p in notes if (p + s) % 12 in DIATONIC)
        if h > max_h: max_h = h; best_shift = s

    # Octave shift as in current code:
    sorted_p = sorted([p + best_shift for p in notes])
    median = sorted_p[len(sorted_p)//2]
    diff = 72 - median
    oct_shift = int(round(diff / 12.0) * 12)

    current_keys = [midi_pitch_to_sky_key_current(p + best_shift + oct_shift) for p in notes]
    folded_keys = [midi_pitch_to_sky_key_octave_folded(p + best_shift) for p in notes]

    print(f"\n--- {os.path.basename(filepath)} --- (Total notes: {len(notes)})")
    print(f"Current method key 0 count: {current_keys.count(0)} ({current_keys.count(0)/len(notes)*100:.1f}%), key 14 count: {current_keys.count(14)} ({current_keys.count(14)/len(notes)*100:.1f}%)")
    print(f"Octave folded key 0 count: {folded_keys.count(0)} ({folded_keys.count(0)/len(notes)*100:.1f}%), key 14 count: {folded_keys.count(14)} ({folded_keys.count(14)/len(notes)*100:.1f}%)")
    print(f"Current key distribution (0..14): {[current_keys.count(k) for k in range(15)]}")
    print(f"Folded key distribution (0..14):  {[folded_keys.count(k) for k in range(15)]}")

test_key_distribution("e:/work/skymusic/midi_downloads/鸳鸯戏_259281.mid")
test_key_distribution("e:/work/skymusic/midi_downloads/反乌托邦_259276.mid")
