import sys
sys.path.append('.')
import demo
import mido

mid = mido.MidiFile('半壶纱.mid')
bpm = demo.get_bpm(mid)
tracks = demo.extract_tracks(mid)
cands, acc = demo.select_melody(tracks, mid.ticks_per_beat)
mel = demo.clean_melody(cands, mid.ticks_per_beat)
all_notes = [n for t in tracks for n in t]
tonic, mode, key_desc = demo.detect_key(mel, all_notes)
refined = demo.refine_melody_with_key(cands, mel, tonic, mode, mid.ticks_per_beat)
if len(refined) >= max(1, int(len(mel) * 0.72)):
    mel = refined
tonic, mode, key_desc = demo.detect_key(mel, all_notes)
shift = demo.choose_normalization_shift(mel, tonic, mode)
oct_shift = demo.choose_best_octave_shift(mel, shift)
mel_events, grid = demo.build_melody_events(mel, shift, oct_shift, mid.ticks_per_beat)
bass_events = demo.build_bass_events(acc, shift, oct_shift, mid.ticks_per_beat, mel_events, grid)
final_events = demo.merge_events(mel_events, bass_events)

print(f"Key: {key_desc}, shift: {shift}, oct_shift: {oct_shift}, grid: {grid}, count: {len(final_events)}")
with open('scripts/py_events.txt', 'w', encoding='utf-8') as f:
    for e in final_events:
        f.write(f"{e['start']},{e['key']},{e['pitch']},{e['dur']},{e['is_melody']}\n")
print("Saved scripts/py_events.txt")
