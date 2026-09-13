import os
import glob
import struct

DIATONIC = {0, 2, 4, 5, 7, 9, 11}

def check_shifts(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    offset = 14
    notes = []
    for t in range(tracks):
        if offset + 8 > len(data): break
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]
        offset += 8
        track_bytes = data[offset:offset+chunk_len]
        offset += chunk_len
        pos = 0; running_status = 0
        while pos < len(track_bytes):
            # VLQ
            delta = 0
            while True:
                if pos >= len(track_bytes): break
                b = track_bytes[pos]; pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if not (b & 0x80): break
            if pos >= len(track_bytes): break
            status = track_bytes[pos]
            if status < 0x80: status = running_status
            else:
                pos += 1
                running_status = status if status < 0xF0 else 0
            if status == 0xFF:
                pos += 1
                l = 0
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
                msg = status & 0xF0
                ch = status & 0x0F
                if msg == 0x90:
                    note = track_bytes[pos]; vel = track_bytes[pos+1]; pos += 2
                    if vel > 0 and ch != 9: notes.append(note)
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    print(f"\nShift comparison for: {os.path.basename(filepath)}")
    shift_hits = []
    for s in range(-6, 7):
        hits = sum(1 for p in notes if ((p + s) % 12) in DIATONIC)
        shift_hits.append((s, hits, hits/len(notes)))
    
    # Sort by hits descending
    shift_hits.sort(key=lambda x: x[1], reverse=True)
    for s, h, r in shift_hits[:5]:
        print(f"  shift={s:+2d}: {h}/{len(notes)} ({r*100:.1f}%)")

for f in sorted(glob.glob("e:/work/skymusic/midi_downloads/*.mid")):
    check_shifts(f)
