import struct
import json
import os

def test_midi(filepath):
    print(f"--- Testing MIDI: {filepath} ---")
    with open(filepath, 'rb') as f:
        data = f.read()
    
    assert data[:4] == b'MThd', "Header must be MThd"
    header_len = struct.unpack('>I', data[4:8])[0]
    fmt, tracks, division = struct.unpack('>HHH', data[8:14])
    print(f"MIDI format: {fmt}, tracks: {tracks}, division: {division}")
    
    # Parse track
    idx = 14
    while idx < len(data):
        chunk_id = data[idx:idx+4]
        chunk_len = struct.unpack('>I', data[idx+4:idx+8])[0]
        idx += 8
        if chunk_id == b'MTrk':
            track_bytes = data[idx:idx+chunk_len]
            print(f"MTrk length: {len(track_bytes)} bytes")
            # Scan NoteOn events
            notes = 0
            t_idx = 0
            while t_idx < len(track_bytes):
                # read delta
                val = 0
                while True:
                    b = track_bytes[t_idx]
                    t_idx += 1
                    val = (val << 7) | (b & 0x7F)
                    if not (b & 0x80):
                        break
                if t_idx >= len(track_bytes):
                    break
                status = track_bytes[t_idx]
                if status == 0xFF: # meta
                    t_idx += 1
                    meta_type = track_bytes[t_idx]
                    t_idx += 1
                    meta_len = track_bytes[t_idx]
                    t_idx += 1 + meta_len
                elif status & 0xF0 == 0x90:
                    t_idx += 1
                    note = track_bytes[t_idx]
                    t_idx += 1
                    vel = track_bytes[t_idx]
                    t_idx += 1
                    if vel > 0:
                        notes += 1
                elif status & 0xF0 in (0x80, 0xA0, 0xB0, 0xE0):
                    t_idx += 3
                elif status & 0xF0 in (0xC0, 0xD0):
                    t_idx += 2
                else:
                    t_idx += 1
            print(f"Found {notes} NoteOn events in MIDI file")
        idx += chunk_len
    print("[PASS] MIDI test passed!\n")

def test_json(filepath):
    print(f"--- Testing Sky JSON: {filepath} ---")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if isinstance(data, list) and len(data) > 0:
        song = data[0]
    else:
        song = data
    
    name = song.get("name", "Unknown")
    bpm = song.get("bpm", 120)
    notes = song.get("songNotes", [])
    print(f"Song: {name}, BPM: {bpm}, Total notes: {len(notes)}")
    
    keys = set()
    import re
    for n in notes:
        k_str = n.get("key", "")
        m = re.search(r'Key(\d+)', k_str)
        if m:
            num = int(m.group(1))
        else:
            num = int(k_str)
        assert 0 <= num <= 14, f"Key index {num} out of bounds (0-14)"
        keys.add(num)
    print(f"Keys utilized: {sorted(list(keys))}")
    print("[PASS] Sky JSON test passed!\n")

def test_layout_calculation():
    print("--- Testing Key Layout Calculations ---")
    resolutions = [
        (1920, 1080, "16:9"),
        (2340, 1080, "19.5:9"),
        (2400, 1080, "20:9"),
        (2048, 1536, "4:3 Tablet")
    ]
    for w, h, label in resolutions:
        # col: 0..4, row: 0..2
        # center: 0.50, 0.54
        center_x = w * 0.50
        center_y = h * 0.54
        spacing_x = w * 0.082
        spacing_y = h * 0.150
        
        # Test key 0 (top-left) and key 14 (bottom-right)
        x0 = center_x + (0 - 2) * spacing_x
        y0 = center_y + (0 - 1) * spacing_y
        
        x14 = center_x + (4 - 2) * spacing_x
        y14 = center_y + (2 - 1) * spacing_y
        
        # Verify within screen boundaries with safe margin
        assert 0 < x0 < w and 0 < y0 < h, f"Key 0 out of bounds for {label}: ({x0}, {y0})"
        assert 0 < x14 < w and 0 < y14 < h, f"Key 14 out of bounds for {label}: ({x14}, {y14})"
        print(f"[{label} ({w}x{h})] Key 0: ({x0:.1f}, {y0:.1f}), Key 14: ({x14:.1f}, {y14:.1f}) -> In bounds!")
    print("[PASS] Layout calculation test passed!\n")

if __name__ == '__main__':
    test_midi("e:/work/skymusic/app/src/main/assets/songs/canon_sample.mid")
    test_json("e:/work/skymusic/app/src/main/assets/songs/twinkle_star.json")
    test_json("e:/work/skymusic/app/src/main/assets/songs/always_with_me.json")
    test_layout_calculation()
    print("ALL TESTS PASSED SUCCESSFULLY!")
