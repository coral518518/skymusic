import struct
import os
import glob

# Krumhansl-Schmuckler Key Profiles
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

PITCH_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def find_key_krumhansl(notes):
    # notes: list of pitch integers (excluding channel 9)
    if not notes: return 0, "C", "major"
    
    # 12 pitch class counts
    counts = [0] * 12
    for p in notes:
        counts[p % 12] += 1
        
    def corr(p1, p2):
        mean1 = sum(p1) / 12.0
        mean2 = sum(p2) / 12.0
        num = sum((p1[i] - mean1) * (p2[i] - mean2) for i in range(12))
        den1 = sum((p1[i] - mean1)**2 for i in range(12))
        den2 = sum((p2[i] - mean2)**2 for i in range(12))
        if den1 == 0 or den2 == 0: return 0
        return num / ((den1 * den2) ** 0.5)

    best_score = -999
    best_tonic = 0
    best_mode = "major"
    best_shift = 0

    for tonic in range(12):
        # Rotate counts so that tonic is at index 0
        rotated = [counts[(tonic + i) % 12] for i in range(12)]
        score_maj = corr(rotated, MAJOR_PROFILE)
        score_min = corr(rotated, MINOR_PROFILE)

        if score_maj > best_score:
            best_score = score_maj
            best_tonic = tonic
            best_mode = "major"
            # To transpose Major key with tonic T to C major (0):
            # (T + shift) % 12 == 0  =>  shift = -T (or 12 - T)
            shift = (12 - tonic) % 12
            if shift > 6: shift -= 12
            best_shift = shift

        if score_min > best_score:
            best_score = score_min
            best_tonic = tonic
            best_mode = "minor"
            # To transpose Minor key with tonic T to A minor (9):
            # (T + shift) % 12 == 9  =>  shift = 9 - T
            shift = (9 - tonic) % 12
            if shift > 6: shift -= 12
            best_shift = shift

    return best_shift, PITCH_NAMES[best_tonic], best_mode

def test_file(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    offset = 14
    notes = []
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
            if status < 0x80: status = running_status
            else:
                pos += 1
                running_status = status if status < 0xF0 else 0
            if status == 0xFF:
                pos += 1; l = 0
                while True:
                    b = track_bytes[pos]; pos += 1; l = (l<<7)|(b&0x7F)
                    if not (b&0x80): break
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
                    if vel > 0 and ch != 9: notes.append(note)
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    shift, tonic, mode = find_key_krumhansl(notes)
    DIATONIC = {0, 2, 4, 5, 7, 9, 11}
    hits = sum(1 for p in notes if ((p + shift) % 12) in DIATONIC)
    print(f"{os.path.basename(filepath)}: Detected Key = {tonic} {mode} (shift={shift:+2d}), Diatonic Hit Rate = {hits/len(notes)*100:.1f}%")

for f in sorted(glob.glob("e:/work/skymusic/midi_downloads/*.mid")):
    test_file(f)
