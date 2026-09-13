import os
import struct
import glob

def parse_midi_file(filepath):
    print(f"\n==========================================")
    print(f"Parsing: {os.path.basename(filepath)}")
    with open(filepath, 'rb') as f:
        data = f.read()

    if data[:4] != b'MThd':
        print("Not MThd")
        return

    header_len = struct.unpack('>I', data[4:8])[0]
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    print(f"Format: {fmt}, Tracks: {tracks}, Division: {division}")

    offset = 8 + header_len
    all_notes = []
    track_info = []

    for t in range(tracks):
        if offset + 8 > len(data):
            break
        chunk_id = data[offset:offset+4]
        chunk_len = struct.unpack('>I', data[offset+4:offset+8])[0]
        offset += 8
        end_pos = offset + chunk_len

        track_bytes = data[offset:end_pos]
        offset = end_pos

        pos = 0
        cur_tick = 0
        running_status = 0
        track_notes = []
        track_name = ""

        while pos < len(track_bytes):
            # VLQ
            delta = 0
            while True:
                if pos >= len(track_bytes): break
                b = track_bytes[pos]
                pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if not (b & 0x80):
                    break
            cur_tick += delta

            if pos >= len(track_bytes): break
            status = track_bytes[pos]
            if status < 0x80:
                if running_status == 0:
                    print(f"  [ERROR] Running status missing at pos {pos}")
                    break
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
                # meta len
                meta_len = 0
                while True:
                    if pos >= len(track_bytes): break
                    b = track_bytes[pos]
                    pos += 1
                    meta_len = (meta_len << 7) | (b & 0x7F)
                    if not (b & 0x80):
                        break
                meta_data = track_bytes[pos:pos+meta_len]
                pos += meta_len
                if meta_type == 0x03:
                    try:
                        track_name = meta_data.decode('utf-8', errors='ignore')
                    except:
                        pass
            elif status in (0xF0, 0xF7):
                sysex_len = 0
                while True:
                    if pos >= len(track_bytes): break
                    b = track_bytes[pos]
                    pos += 1
                    sysex_len = (sysex_len << 7) | (b & 0x7F)
                    if not (b & 0x80):
                        break
                pos += sysex_len
            else:
                msg_type = status & 0xF0
                channel = status & 0x0F
                if msg_type == 0x90:
                    if pos + 1 >= len(track_bytes): break
                    note = track_bytes[pos]
                    vel = track_bytes[pos+1]
                    pos += 2
                    if vel > 0:
                        track_notes.append((cur_tick, channel, note, vel))
                elif msg_type == 0x80:
                    pos += 2
                elif msg_type in (0xA0, 0xB0, 0xE0):
                    pos += 2
                elif msg_type in (0xC0, 0xD0):
                    pos += 1
                else:
                    print(f"  [WARN] Unknown status {hex(status)} at pos {pos}")
                    break

        track_info.append((track_name, len(track_notes)))
        all_notes.extend(track_notes)

    print(f"Total NoteOn events: {len(all_notes)}")
    for idx, (name, cnt) in enumerate(track_info):
        print(f"  Track {idx}: '{name}', notes: {cnt}")

    # Inspect channels
    channels = {}
    for tick, ch, note, vel in all_notes:
        channels[ch] = channels.get(ch, 0) + 1
    print(f"Channel counts: {channels}")

    # Inspect pitch distribution
    pitches = [n[2] for n in all_notes if n[1] != 9] # exclude drum ch 9 (10th)
    if pitches:
        min_p = min(pitches)
        max_p = max(pitches)
        print(f"Pitch range (excl ch 9): min={min_p}, max={max_p}")
        below_60 = len([p for p in pitches if p < 60])
        above_84 = len([p for p in pitches if p > 84])
        print(f"Total non-drum notes: {len(pitches)}, <60 (below C4): {below_60} ({below_60/len(pitches)*100:.1f}%), >84: {above_84}")

for f in glob.glob("e:/work/skymusic/midi_downloads/*.mid"):
    parse_midi_file(f)
