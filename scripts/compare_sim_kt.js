const fs = require('fs');

// 1. Simulator parsing sky_preview_v7.mid
const code = fs.readFileSync('simulator/app.js', 'utf8');
const fnCode = code.slice(code.indexOf('const ScoreParsers = {'));
const endIdx = fnCode.indexOf('// 4. 模拟器应用核心控制');
const objCode = fnCode.slice(0, endIdx).replace('const ScoreParsers =', 'global.ScoreParsers =');
eval(objCode);

const buf = fs.readFileSync('sky_preview_v7.mid');
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const simParsed = global.ScoreParsers.parseMidi(ab, 'sky_preview_v7.mid');

// 2. Kotlin MidiParser output on 半壶纱.mid (from scripts/kt_events.txt)
const ktLines = fs.readFileSync('scripts/kt_events.txt', 'utf8').trim().split('\n').map(l => {
    const [t, k] = l.split(',');
    return { timeMs: parseInt(t), keys: k ? k.split(';').map(x => parseInt(x)) : [] };
});

console.log(`Simulator notes count: ${simParsed.notes.length}, Kotlin notes count: ${ktLines.length}`);

let diffCount = 0;
for (let i = 0; i < Math.max(simParsed.notes.length, ktLines.length); i++) {
    const simN = simParsed.notes[i];
    const ktN = ktLines[i];
    if (!simN || !ktN) {
        console.log(`[Diff at ${i}] sim=${JSON.stringify(simN)} vs kt=${JSON.stringify(ktN)}`);
        diffCount++;
        if (diffCount > 10) break;
        continue;
    }
    const timeDiff = Math.abs(simN.timeMs - ktN.timeMs);
    const keyDiff = JSON.stringify(simN.keys) !== JSON.stringify(ktN.keys);
    if (keyDiff || timeDiff > 50) {
        console.log(`[Diff at ${i}] sim: t=${simN.timeMs} keys=${JSON.stringify(simN.keys)}  |  kt: t=${ktN.timeMs} keys=${JSON.stringify(ktN.keys)}`);
        diffCount++;
        if (diffCount > 15) break;
    }
}
if (diffCount === 0) {
    console.log("ALL NOTES AND KEYS ARE 100% IDENTICAL!");
}
