// audio.js — synthétiseur d'effets sonores via la Web Audio API.
//
// Aucun fichier audio à charger : tous les sons sont générés à la volée avec
// des oscillateurs (tons) et du bruit blanc filtré (explosions, impacts).
// Le contexte audio est créé paresseusement au premier appel (après une
// interaction utilisateur, pour respecter la politique autoplay).

(function (global) {
  "use strict";

  let ctx = null;
  let masterGain = null;
  let enabled = true;

  function _ensureCtx() {
    if (ctx) return ctx;
    try {
      const AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      masterGain = ctx.createGain();
      masterGain.gain.value = 0.35;   // volume global
      masterGain.connect(ctx.destination);
    } catch (e) {
      ctx = null;
    }
    return ctx;
  }

  // L'AudioContext doit être créé/resumé après une interaction utilisateur.
  // On branche un one-shot sur le premier clic/touche.
  function unlock() {
    const c = _ensureCtx();
    if (c && c.state === "suspended") c.resume();
  }
  if (typeof window !== "undefined") {
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
  }

  // --- Helpers -----------------------------------------------------------

  // Joue un ton simple (oscillator + envelope).
  function _tone(opts) {
    const c = _ensureCtx();
    if (!c || !enabled) return;
    const {
      freq = 440, freqEnd = null, type = "sine",
      duration = 0.12, volume = 0.4,
      attack = 0.005, release = 0.05,
      startTime = 0,
    } = opts;
    const t0 = c.currentTime + startTime;
    const t1 = t0 + duration;
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (freqEnd != null) osc.frequency.exponentialRampToValueAtTime(Math.max(1, freqEnd), t1);
    // Envelope ADSR simplifiée.
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(volume, t0 + attack);
    g.gain.setValueAtTime(volume, t1 - release);
    g.gain.exponentialRampToValueAtTime(0.0001, t1);
    osc.connect(g);
    g.connect(masterGain);
    osc.start(t0);
    osc.stop(t1 + 0.02);
  }

  // Joue un burst de bruit filtré (explosions, impacts).
  function _noise(opts) {
    const c = _ensureCtx();
    if (!c || !enabled) return;
    const {
      duration = 0.3, volume = 0.5,
      filterType = "lowpass", filterFreq = 1200, filterQ = 1,
      startTime = 0,
    } = opts;
    const t0 = c.currentTime + startTime;
    const t1 = t0 + duration;
    // Buffer de bruit blanc.
    const sr = c.sampleRate;
    const frames = Math.floor(sr * duration);
    const buf = c.createBuffer(1, frames, sr);
    const data = buf.getChannelData(0);
    for (let i = 0; i < frames; i++) data[i] = Math.random() * 2 - 1;
    const src = c.createBufferSource();
    src.buffer = buf;
    const filter = c.createBiquadFilter();
    filter.type = filterType;
    filter.frequency.setValueAtTime(filterFreq, t0);
    filter.frequency.exponentialRampToValueAtTime(Math.max(80, filterFreq * 0.3), t1);
    filter.Q.value = filterQ;
    const g = c.createGain();
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(volume, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t1);
    src.connect(filter);
    filter.connect(g);
    g.connect(masterGain);
    src.start(t0);
    src.stop(t1 + 0.02);
  }

  // --- API publique ------------------------------------------------------

  const Sfx = {
    setEnabled(v) { enabled = !!v; },
    isEnabled() { return enabled; },

    // Pas de son pour le déplacement : ce serait trop répétitif à 9Hz.
    // On met un petit "clic" très court et très bas qu'on peut ignorer.

    move() {
      // Trop répétitif : on ne joue rien. (Gardé pour API future.)
    },

    shovel() {
      // Coup de pelle : bruit court et grave + petit ton.
      _noise({ duration: 0.12, volume: 0.25, filterType: "lowpass", filterFreq: 800, filterQ: 2 });
      _tone({ freq: 180, freqEnd: 90, type: "square", duration: 0.08, volume: 0.15 });
    },

    knife() {
      // Coup de couteau : aigu, court, type "swish".
      _noise({ duration: 0.08, volume: 0.2, filterType: "highpass", filterFreq: 2000, filterQ: 0.7 });
      _tone({ freq: 1200, freqEnd: 600, type: "triangle", duration: 0.06, volume: 0.2 });
    },

    bombPlace() {
      // Pose de bombe : petit "clic" électronique.
      _tone({ freq: 220, freqEnd: 180, type: "square", duration: 0.05, volume: 0.2 });
    },

    explosion() {
      // Explosion : gros bruit bas + ton descendant.
      _noise({ duration: 0.5, volume: 0.6, filterType: "lowpass", filterFreq: 1500, filterQ: 0.7 });
      _tone({ freq: 120, freqEnd: 40, type: "sawtooth", duration: 0.4, volume: 0.3, attack: 0.01, release: 0.2 });
    },

    damage() {
      // Dégâts subis : ton aigu descendant + léger bruit.
      _tone({ freq: 800, freqEnd: 300, type: "sawtooth", duration: 0.18, volume: 0.3 });
      _noise({ duration: 0.1, volume: 0.15, filterType: "bandpass", filterFreq: 1000, filterQ: 1 });
    },

    death() {
      // Mort : ton descendant long.
      _tone({ freq: 400, freqEnd: 80, type: "sawtooth", duration: 0.5, volume: 0.35, attack: 0.01, release: 0.15 });
    },

    respawn() {
      // Respawn : ton montant doux.
      _tone({ freq: 200, freqEnd: 600, type: "sine", duration: 0.25, volume: 0.25 });
    },

    win() {
      // Victoire : arpege majeur montant.
      _tone({ freq: 523, type: "triangle", duration: 0.15, volume: 0.3, startTime: 0 });
      _tone({ freq: 659, type: "triangle", duration: 0.15, volume: 0.3, startTime: 0.12 });
      _tone({ freq: 784, type: "triangle", duration: 0.15, volume: 0.3, startTime: 0.24 });
      _tone({ freq: 1047, type: "triangle", duration: 0.35, volume: 0.35, startTime: 0.36 });
    },

    lose() {
      // Défaite : arpege mineur descendant.
      _tone({ freq: 440, type: "sawtooth", duration: 0.18, volume: 0.3, startTime: 0 });
      _tone({ freq: 349, type: "sawtooth", duration: 0.18, volume: 0.3, startTime: 0.16 });
      _tone({ freq: 262, type: "sawtooth", duration: 0.5, volume: 0.35, startTime: 0.32 });
    },

    connect() {
      // Connexion WS établie : petit "blip".
      _tone({ freq: 660, type: "sine", duration: 0.06, volume: 0.2 });
    },

    click() {
      // Clic UI générique.
      _tone({ freq: 440, type: "square", duration: 0.03, volume: 0.15 });
    },
  };

  global.Sfx = Sfx;
})(typeof window !== "undefined" ? window : this);
