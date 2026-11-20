// Sound for the TV: effects and calm background music, all synthesised with WebAudio
// (no audio files, nothing to download or license).
//
//   sound.apply({ music, sfx, volume })   settings coming from the server (the host's phone)
//   sound.play("acierto")                 one effect
//   sound.onLock(cb)                      cb(true) while the browser still blocks audio
//
// Browsers only allow audio after a click or key press, so the first one on the TV unlocks it.

const AudioCtx = window.AudioContext || window.webkitAudioContext;

let ctx = null;
let master = null;
let sfxBus = null;
let musicOut = null;
let reverb = null;
let settings = { music: true, sfx: true, volume: 70 };
let localMute = false;
const lockListeners = new Set();

// ----- context ---------------------------------------------------------------------------
function makeReverb(c) {
  const seconds = 2.8;
  const length = Math.floor(c.sampleRate * seconds);
  const buffer = c.createBuffer(2, length, c.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const data = buffer.getChannelData(ch);
    for (let i = 0; i < length; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, 2.6);
  }
  const node = c.createConvolver();
  node.buffer = buffer;
  return node;
}

function ensure() {
  if (ctx || !AudioCtx) return ctx;
  ctx = new AudioCtx();
  master = ctx.createGain();
  master.gain.value = 0;
  master.connect(ctx.destination);
  sfxBus = ctx.createGain();
  sfxBus.connect(master);
  musicOut = ctx.createGain();
  musicOut.gain.value = 0.55;
  musicOut.connect(master);
  reverb = makeReverb(ctx);
  const wet = ctx.createGain();
  wet.gain.value = 0.9;
  reverb.connect(wet).connect(musicOut);
  ctx.addEventListener("statechange", notifyLock);
  refresh();
  return ctx;
}

function locked() { return !!ctx && ctx.state !== "running"; }
function notifyLock() { for (const cb of lockListeners) cb(locked()); }

function unlock() {
  ensure();
  if (ctx && ctx.state !== "running") ctx.resume().then(() => { refresh(); notifyLock(); }, () => {});
}
for (const ev of ["pointerdown", "keydown", "touchstart"]) addEventListener(ev, unlock, { passive: true });
document.addEventListener("DOMContentLoaded", () => { ensure(); unlock(); });

// ----- volume / on-off -------------------------------------------------------------------
function refresh() {
  if (!ctx) return;
  const level = localMute ? 0 : Math.pow(settings.volume / 100, 1.6) * 0.9;
  master.gain.setTargetAtTime(level, ctx.currentTime, 0.08);
  if (settings.music && !localMute) startMusic();
  else stopMusic();
}

// ----- effects -----------------------------------------------------------------------------
function tone(freq, start, dur, { type = "sine", vol = 0.25, glide = 0, attack = 0.01, to = sfxBus } = {}) {
  const t = ctx.currentTime + start;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (glide) osc.frequency.exponentialRampToValueAtTime(Math.max(20, freq * glide), t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(vol, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(g).connect(to);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

const NOTE = (n) => 440 * Math.pow(2, (n - 69) / 12); // MIDI number -> Hz

const EFFECTS = {
  acierto() { [72, 76, 79].forEach((n, i) => tone(NOTE(n), i * 0.09, 0.45, { type: "triangle", vol: 0.22 })); },
  fallo() { tone(NOTE(55), 0, 0.5, { type: "sawtooth", vol: 0.1, glide: 0.7 }); tone(NOTE(50), 0.16, 0.6, { type: "sawtooth", vol: 0.09, glide: 0.7 }); },
  revelar() { tone(NOTE(60), 0, 0.7, { type: "sine", vol: 0.2 }); tone(NOTE(67), 0.05, 0.7, { type: "sine", vol: 0.16 }); tone(NOTE(76), 0.1, 0.9, { type: "sine", vol: 0.1 }); },
  empieza() { tone(300, 0, 0.35, { type: "triangle", vol: 0.18, glide: 2.4 }); },
  respuesta() { tone(NOTE(79), 0, 0.12, { type: "sine", vol: 0.16 }); },
  tic() { tone(1100, 0, 0.06, { type: "square", vol: 0.06 }); },
  ticfinal() { tone(1500, 0, 0.12, { type: "square", vol: 0.08 }); },
  jugador() { tone(NOTE(81), 0, 0.3, { type: "sine", vol: 0.18 }); tone(NOTE(88), 0.1, 0.45, { type: "sine", vol: 0.14 }); },
  turno() { tone(NOTE(84), 0, 0.8, { type: "sine", vol: 0.16 }); tone(NOTE(91), 0, 0.8, { type: "sine", vol: 0.06 }); },
  paso() { tone(NOTE(72), 0, 0.09, { type: "triangle", vol: 0.14 }); },
  evento() { [67, 71, 74, 71, 76].forEach((n, i) => tone(NOTE(n), i * 0.07, 0.18, { type: "square", vol: 0.07 })); },
  estrella() { [84, 88, 91, 96].forEach((n, i) => tone(NOTE(n), i * 0.06, 0.5, { type: "sine", vol: 0.14 })); },
  duelo() { tone(NOTE(52), 0, 0.25, { type: "sawtooth", vol: 0.1 }); tone(NOTE(55), 0.18, 0.4, { type: "sawtooth", vol: 0.1 }); },
  ruleta() { tone(900 + Math.random() * 60, 0, 0.05, { type: "triangle", vol: 0.12 }); },
  moneda() {
    tone(500, 0, 0.5, { type: "sine", vol: 0.07, glide: 3 });
    tone(NOTE(96), 2.6, 0.9, { type: "sine", vol: 0.14 });
    tone(NOTE(103), 2.6, 0.6, { type: "sine", vol: 0.07 });
  },
  desempate() { [0, 0.3, 0.6].forEach((d) => tone(130, d, 0.35, { type: "sine", vol: 0.35, glide: 0.35 })); },
  fanfarria() {
    [[60, 0], [64, 0.14], [67, 0.28], [72, 0.42]].forEach(([n, d]) => tone(NOTE(n), d, 0.4, { type: "triangle", vol: 0.2 }));
    [60, 64, 67, 72, 76].forEach((n) => tone(NOTE(n), 0.62, 1.8, { type: "triangle", vol: 0.12, attack: 0.04 }));
  },
};

function play(name) {
  if (!settings.sfx || localMute) return;
  ensure();
  if (!ctx || ctx.state !== "running") return;
  try { EFFECTS[name]?.(); } catch { /* a sound must never break the game */ }
}

// ----- background music ------------------------------------------------------------------------
// Four slow chords (C - Am - F - G), each one a bar of 8 s: a soft pad plus a few notes of the
// pentatonic scale plucked at random, through a delay and reverb. It never repeats exactly.
const BAR = 8;
const CHORDS = [[48, 55, 64, 67], [45, 57, 64, 69], [41, 57, 60, 65], [43, 55, 62, 67]];
const PENTA = [72, 74, 76, 79, 81, 84];
let bus = null;
let timer = 0;
let nextBar = 0;
let barNo = 0;

function startMusic() {
  if (bus || !ctx) return;
  bus = ctx.createGain();
  bus.gain.value = 0.0001;
  bus.gain.exponentialRampToValueAtTime(1, ctx.currentTime + 2);
  const delay = ctx.createDelay(1.5);
  delay.delayTime.value = 0.46;
  const feedback = ctx.createGain();
  feedback.gain.value = 0.38;
  delay.connect(feedback).connect(delay);
  const delayOut = ctx.createGain();
  delayOut.gain.value = 0.35;
  bus.connect(musicOut);
  bus.connect(reverb);
  bus.__echo = delay;
  delay.connect(delayOut).connect(musicOut);
  nextBar = ctx.currentTime + 0.3;
  barNo = 0;
  timer = setInterval(scheduleAhead, 1000);
  scheduleAhead();
}

function stopMusic() {
  if (!bus) return;
  clearInterval(timer);
  const old = bus;
  bus = null;
  old.gain.cancelScheduledValues(ctx.currentTime);
  old.gain.setTargetAtTime(0.0001, ctx.currentTime, 0.4);
  setTimeout(() => { try { old.disconnect(); old.__echo.disconnect(); } catch { /* already gone */ } }, 3000);
}

function scheduleAhead() {
  if (!bus || !ctx || ctx.state !== "running") return;
  if (nextBar < ctx.currentTime) nextBar = ctx.currentTime + 0.1;
  while (nextBar < ctx.currentTime + 3) {
    scheduleBar(nextBar, CHORDS[barNo % CHORDS.length]);
    nextBar += BAR;
    barNo++;
  }
}

function scheduleBar(at, chord) {
  const out = bus;
  const now = ctx.currentTime;
  for (const n of chord) { // pad: slow attack and release
    for (const detune of [-6, 6]) {
      const osc = ctx.createOscillator();
      const filter = ctx.createBiquadFilter();
      const g = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = NOTE(n);
      osc.detune.value = detune;
      filter.type = "lowpass";
      filter.frequency.value = 900;
      g.gain.setValueAtTime(0.0001, at);
      g.gain.linearRampToValueAtTime(0.05, at + 2.4);
      g.gain.setValueAtTime(0.05, at + BAR - 2.2);
      g.gain.linearRampToValueAtTime(0.0001, at + BAR + 1.8);
      osc.connect(filter).connect(g).connect(out);
      osc.start(at);
      osc.stop(at + BAR + 2);
    }
  }
  const notes = 3 + Math.floor(Math.random() * 3); // a few plucked notes
  for (let i = 0; i < notes; i++) {
    const t = at + 0.6 + Math.random() * (BAR - 1.5);
    if (t < now) continue;
    const midi = PENTA[Math.floor(Math.random() * PENTA.length)];
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = NOTE(midi);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.09, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 2.4);
    osc.connect(g);
    g.connect(out);
    g.connect(out.__echo);
    osc.start(t);
    osc.stop(t + 2.5);
  }
}

// ----- public API ------------------------------------------------------------------------------
export const sound = {
  apply(next) {
    if (!next) return;
    settings = { music: next.music !== false, sfx: next.sfx !== false, volume: Number.isFinite(next.volume) ? next.volume : 70 };
    refresh();
  },
  play,
  /** Quiet the music a bit while a question is open. */
  duck(on) {
    if (!ctx) return;
    musicOut.gain.setTargetAtTime(on ? 0.3 : 0.55, ctx.currentTime, 0.6);
  },
  /** Local mute for this TV only (key M), on top of the host's setting. */
  toggleLocalMute() {
    localMute = !localMute;
    refresh();
    return localMute;
  },
  onLock(cb) { lockListeners.add(cb); cb(locked() || !ctx); },
  unlock,
  /** For tests: the audio graph's master node and context. */
  _debug() { return { ctx, master }; },
};
