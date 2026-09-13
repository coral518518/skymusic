import sys
sys.path.append('.')
import mido
import demo

mid = mido.MidiFile('半壶纱.mid')
tracks = demo.extract_tracks(mid)
for t_idx, t in enumerate(tracks):
    print(f"Track {t_idx} notes around 25900-26700:")
    for n in t:
        if 25900 <= n['start'] <= 26700:
            print(f"  start={n['start']}, pitch={n['pitch']}, dur={n['dur']}, vel={n['velocity']}")
