import struct

KEY_NAMES = [
    "1", "2", "3", "4", "5", "6", "7",
    "+1", "+2", "+3", "+4", "+5", "+6", "+7",
    "++1"
]
SKY_PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]

def test_ruguo():
    with open("e:/work/skymusic/midi_downloads/如果可以-韋禮安_259259.mid", 'rb') as f: data = f.read()
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
                msg = status & 0xF0; ch = status & 0x0F
                if msg == 0x90:
                    note = track_bytes[pos]; vel = track_bytes[pos+1]; pos += 2
                    if vel > 0 and ch != 9: notes.append((cur_tick, ch, note, vel))
                elif msg in (0x80, 0xA0, 0xB0, 0xE0): pos += 2
                elif msg in (0xC0, 0xD0): pos += 1

    # In 如果可以, which track or channel has the melody?
    # Let's group by track/channel to see:
    ch_counts = {}
    for tick, ch, note, vel in notes:
        ch_counts[ch] = ch_counts.get(ch, 0) + 1
    print("Channel counts:", ch_counts)

    # With shift=-3 and oct_shift=+12:
    def map_p(p):
        t = p - 3 + 12
        while t < 60: t += 12
        while t > 84: t -= 12
        # map to sky
        min_d = 999; best_k = 0
        for i, target in enumerate(SKY_PITCHES):
            d = abs(t - target)
            if d < min_d: min_d = d; best_k = i
        return best_k

    # Let's inspect first 50 notes
    mapped = [KEY_NAMES[map_p(n[2])] for n in notes[:50]]
    print("Mapped first 50 notes:")
    print(" ".join(mapped))

test_ruguo()
