import struct
import os

def write_varlen(val):
    buf = bytearray()
    buf.append(val & 0x7F)
    val >>= 7
    while val > 0:
        buf.append((val & 0x7F) | 0x80)
        val >>= 7
    return bytes(reversed(buf))

def create_midi(filename, notes, tempo_bpm=120, ppq=480):
    # Header Chunk: MThd, length=6, format=0, tracks=1, division=ppq
    header = b'MThd' + struct.pack('>IHHH', 6, 0, 1, ppq)
    
    # Track Chunk
    track_data = bytearray()
    
    # Tempo event: 0xFF 0x51 0x03 (us per quarter note)
    us_per_beat = int(60_000_000 / tempo_bpm)
    track_data += b'\x00\xFF\x51\x03' + struct.pack('>I', us_per_beat)[1:]
    
    # Track Name
    track_name = b"Canon in D"
    track_data += b'\x00\xFF\x03' + write_varlen(len(track_name)) + track_name

    # Notes: list of (start_tick, pitch, duration_ticks, velocity)
    # Turn into events: (tick, event_type, pitch, velocity)
    events = []
    for start, pitch, dur, vel in notes:
        events.append((start, 0x90, pitch, vel))       # Note On
        events.append((start + dur, 0x80, pitch, 0))   # Note Off
    
    events.sort(key=lambda x: (x[0], 0 if x[1] == 0x80 else 1))
    
    last_tick = 0
    for tick, status, pitch, vel in events:
        delta = tick - last_tick
        track_data += write_varlen(delta)
        track_data += bytes([status, pitch, vel])
        last_tick = tick
        
    # End of Track: 0xFF 0x2F 0x00
    track_data += b'\x00\xFF\x2F\x00'
    
    track = b'MTrk' + struct.pack('>I', len(track_data)) + track_data
    
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'wb') as f:
        f.write(header + track)
    print(f"MIDI created: {filename} ({len(header + track)} bytes)")

if __name__ == '__main__':
    # Canon in D notes: (tick, pitch, dur, vel)
    # Pachelbel Canon theme in C major for Sky: C E G, G B D, A C E, E G B, F A C, C E G, F A C, G B D
    ppq = 480
    canon_notes = [
        (0 * ppq, 72, ppq, 90),   # C5
        (0 * ppq, 48, ppq*2, 80), # C3 bass
        (1 * ppq, 71, ppq, 90),   # B4
        (2 * ppq, 69, ppq, 90),   # A4
        (2 * ppq, 45, ppq*2, 80), # A2 bass
        (3 * ppq, 67, ppq, 90),   # G4
        (4 * ppq, 65, ppq, 90),   # F4
        (4 * ppq, 41, ppq*2, 80), # F2 bass
        (5 * ppq, 64, ppq, 90),   # E4
        (6 * ppq, 65, ppq, 90),   # F4
        (6 * ppq, 43, ppq*2, 80), # G2 bass
        (7 * ppq, 67, ppq, 90),   # G4
        # Running notes
        (8 * ppq, 72, int(ppq*0.5), 90),
        (8.5 * ppq, 74, int(ppq*0.5), 90),
        (9 * ppq, 76, int(ppq*0.5), 90),
        (9.5 * ppq, 74, int(ppq*0.5), 90),
        (10 * ppq, 72, int(ppq*0.5), 90),
        (10.5 * ppq, 71, int(ppq*0.5), 90),
        (11 * ppq, 69, int(ppq*0.5), 90),
        (11.5 * ppq, 67, int(ppq*0.5), 90),
        (12 * ppq, 65, int(ppq*0.5), 90),
        (12.5 * ppq, 67, int(ppq*0.5), 90),
        (13 * ppq, 69, int(ppq*0.5), 90),
        (13.5 * ppq, 71, int(ppq*0.5), 90),
        (14 * ppq, 72, ppq*2, 95),
        (14 * ppq, 60, ppq*2, 85),
        (14 * ppq, 48, ppq*2, 80)
    ]
    canon_notes = [(int(t), p, int(d), v) for t, p, d, v in canon_notes]
    create_midi("e:/work/skymusic/app/src/main/assets/songs/canon_sample.mid", canon_notes, tempo_bpm=110, ppq=ppq)
