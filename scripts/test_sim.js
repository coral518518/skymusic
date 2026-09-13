const fs = require('fs');

const code = fs.readFileSync('simulator/app.js', 'utf8');
const fnCode = code.slice(code.indexOf('const ScoreParsers = {'));
const endIdx = fnCode.indexOf('// 4. 模拟器应用核心控制');
const objCode = fnCode.slice(0, endIdx).replace('const ScoreParsers =', 'global.ScoreParsers =');
eval(objCode);

const buf = fs.readFileSync('sky_preview_v7.mid');
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const parsed = global.ScoreParsers.parseMidi(ab, 'sky_preview_v7.mid');

console.log('Web simulator parsed sky_preview_v7.mid:');
console.log('BPM:', parsed.bpm);
console.log('Parsed count:', parsed.notes.length);
console.log('First 15 notes:');
parsed.notes.slice(0, 15).forEach(n => console.log(JSON.stringify(n)));
