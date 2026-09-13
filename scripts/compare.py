import sys
sys.path.append('.')
import mido

mid = mido.MidiFile('半壶纱.mid')
ppq = mid.ticks_per_beat
tempo = 500000
for t in mid.tracks:
    for m in t:
        if m.type == 'set_tempo':
            tempo = m.tempo
            break

def tick_to_ms(tick):
    return round((tick * tempo) / (ppq * 1000))

with open('scripts/py_events.txt') as f:
    py_lines = [l.strip().split(',') for l in f if l.strip()]

with open('scripts/kt_events.txt') as f:
    kt_lines = [l.strip().split(',') for l in f if l.strip()]

print(f"py count: {len(py_lines)}, kt count: {len(kt_lines)}")

# Let's compare first 20 events
for i in range(min(len(py_lines), len(kt_lines), 20)):
    py_t = tick_to_ms(int(py_lines[i][0]))
    py_key = py_lines[i][1]
    kt_t = kt_lines[i][0]
    kt_key = kt_lines[i][1]
    print(f"[{i:02d}] PY: tick={py_lines[i][0]} (ms~{py_t}) key={py_key}  |  KT: ms={kt_t} key={kt_key}")
