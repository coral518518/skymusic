import os
import struct

# Let's inspect the actual notes and tonic of 鸳鸯戏_259281.mid
def inspect_song(filepath):
    with open(filepath, 'rb') as f: data = f.read()
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    offset = 14
    notes = []
    tempo_bpm = 120
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
                meta_type = track_bytes[pos]; pos += 1
                l = 0
                while True:
                    b = track_bytes[pos]; pos += 1; l = (l<<7)|(b&0x7F)
                    if not (b&0x80): break
                if meta_type == 0x51 and l >= 3:
                    us = (track_bytes[pos]<<16)|(track_bytes[pos+1]<<8)|track_bytes[pos+2]
                    tempo_bpm = round(60000000 / us)
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
                        notes.append((cur_tick, note, vel))
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    print(f"File: {os.path.basename(filepath)}, BPM: {tempo_bpm}, Notes: {len(notes)}")
    # Print pitch class histogram:
    pitch_classes = [n[1] % 12 for n in notes]
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    hist = {names[i]: pitch_classes.count(i) for i in range(12)}
    print("Pitch Class Histogram:", {k: v for k, v in hist.items() if v > 0})

inspect_song("e:/work/skymusic/midi_downloads/鸳鸯戏_259281.mid")
inspect_song("e:/work/skymusic/midi_downloads/如果可以-韋禮安_259259.mid")
inspect_song("e:/work/skymusic/midi_downloads/潮汐（DJ版）_259271.mid")
inspect_song("e:/work/skymusic/midi_downloads/反乌托邦_259276.mid")
