import os
import glob

DIATONIC_SET = {0, 2, 4, 5, 7, 9, 11} # C D E F G A B
PENTATONIC_SET = {0, 2, 4, 7, 9}      # 1 2 3 5 6

# Sky keys pitches: 60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84
# Notice: Key of C natural major has notes (mod 12):
# C=0, D=2, E=4, F=5, G=7, A=9, B=11
SKY_PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]

def analyze_song_pitches(filepath):
    import struct
    with open(filepath, 'rb') as f:
        data = f.read()

    header_len = struct.unpack('>I', data[4:8])[0]
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    offset = 8 + header_len

    notes = []
    tempo_changes = [(0, 500000)]

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
                if status < 0xF0:
                    running_status = status
                else:
                    running_status = 0

            if status == 0xFF:
                if pos >= len(track_bytes): break
                meta_type = track_bytes[pos]
                pos += 1
                meta_len = 0
                while True:
                    if pos >= len(track_bytes): break
                    b = track_bytes[pos]
                    pos += 1
                    meta_len = (meta_len << 7) | (b & 0x7F)
                    if not (b & 0x80): break
                if meta_type == 0x51 and meta_len >= 3:
                    us = (track_bytes[pos] << 16) | (track_bytes[pos+1] << 8) | track_bytes[pos+2]
                    tempo_changes.append((cur_tick, us))
                pos += meta_len
            elif status in (0xF0, 0xF7):
                sysex_len = 0
                while True:
                    if pos >= len(track_bytes): break
                    b = track_bytes[pos]
                    pos += 1
                    sysex_len = (sysex_len << 7) | (b & 0x7F)
                    if not (b & 0x80): break
                pos += sysex_len
            else:
                msg_type = status & 0xF0
                channel = status & 0x0F
                if msg_type == 0x90:
                    if pos + 1 >= len(track_bytes): break
                    note = track_bytes[pos]
                    vel = track_bytes[pos+1]
                    pos += 2
                    if vel > 0 and channel != 9: # exclude drums
                        notes.append((cur_tick, note, vel))
                elif msg_type == 0x80:
                    pos += 2
                elif msg_type in (0xA0, 0xB0, 0xE0):
                    pos += 2
                elif msg_type in (0xC0, 0xD0):
                    pos += 1

    print(f"\n--- {os.path.basename(filepath)} --- (Total melodic notes: {len(notes)})")
    # Test best transpose
    pitches = [n[1] for n in notes]
    best_shift = 0
    max_hits = -1
    for s in range(-6, 7):
        hits = sum(1 for p in pitches if ((p + s) % 12) in DIATONIC_SET)
        if hits > max_hits:
            max_hits = hits
            best_shift = s
    print(f"Current findBestTranspose: shift={best_shift}, hit_rate={max_hits/len(pitches)*100:.1f}%")

    # What if we test Krumhansl-Schmuckler Key-Finding Algorithm (or profile correlation)?
    # Let's count pitch class distribution (weighted by note counts or duration):
    pc_counts = [0] * 12
    for p in pitches:
        pc_counts[p % 12] += 1
    print(f"Pitch class distribution: {pc_counts}")

for f in glob.glob("e:/work/skymusic/midi_downloads/*.mid"):
    analyze_song_pitches(f)
