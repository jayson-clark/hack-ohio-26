// Speaks commander_speech in the console window with the Web Speech API
// (voice mode "console"; see engine/commander/voice.py for the same rules).
//
// - A new answer interrupts anything being said.
// - Sentences of one answer queue up in order.
// - A briefing waits for an answer to finish; only the newest briefing waits.
// - Urgent briefings start with a short radio tone.
// - Push-to-talk calls interrupt() so the commander stops talking.

import type { CommanderSpeech } from "./protocol";

const RATE = 1.08;

interface Line {
  utterance: string;
  kind: CommanderSpeech["kind"];
  text: string;
  urgent: boolean;
}

let current: { utterance: string; kind: Line["kind"] } | null = null;
let queue: Line[] = []; // the rest of the current utterance
let waiting: Line | null = null; // at most one briefing
let speaking = false;
let voice: SpeechSynthesisVoice | null = null;

export const speechSupported = typeof window !== "undefined" && "speechSynthesis" in window;

function pickVoice() {
  if (!speechSupported) return;
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
  const preferred = ["Samantha", "Daniel", "Google US English", "Alex"];
  voice =
    preferred.map((name) => voices.find((v) => v.name.includes(name))).find(Boolean) ??
    voices.find((v) => v.lang === "en-US") ??
    voices[0] ??
    null;
}
if (speechSupported) {
  pickVoice();
  window.speechSynthesis.onvoiceschanged = pickVoice;
}

/** A short two-tone radio chirp, so a briefing doesn't start mid-word out of nowhere. */
function tone(): Promise<void> {
  return new Promise((resolve) => {
    try {
      const ctx = new AudioContext();
      const gain = ctx.createGain();
      gain.gain.value = 0.06;
      gain.connect(ctx.destination);
      [880, 1320].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        osc.type = "square";
        osc.frequency.value = freq;
        osc.connect(gain);
        osc.start(ctx.currentTime + i * 0.09);
        osc.stop(ctx.currentTime + i * 0.09 + 0.07);
      });
      setTimeout(() => {
        ctx.close();
        resolve();
      }, 220);
    } catch {
      resolve();
    }
  });
}

function next() {
  if (!queue.length && waiting) {
    current = { utterance: waiting.utterance, kind: waiting.kind };
    queue.push(waiting);
    waiting = null;
  }
  const line = queue.shift();
  if (!line) {
    current = null;
    speaking = false;
    return;
  }
  speaking = true;
  const say = () => {
    const u = new SpeechSynthesisUtterance(line.text);
    if (voice) u.voice = voice;
    u.rate = RATE;
    u.onend = u.onerror = () => {
      if (current?.utterance === line.utterance) next();
    };
    window.speechSynthesis.speak(u);
  };
  if (line.urgent && line.kind === "briefing") tone().then(say);
  else say();
}

export function speak(msg: CommanderSpeech) {
  if (!speechSupported) return;
  const line: Line = { utterance: msg.utterance, kind: msg.kind, text: msg.text, urgent: msg.urgent };
  if (line.kind === "answer") {
    if (current?.utterance !== line.utterance) {
      interrupt();
      current = { utterance: line.utterance, kind: "answer" };
    }
    queue.push(line);
  } else if (speaking && (current?.kind === "answer" || current?.utterance === line.utterance)) {
    waiting = line;
    return;
  } else {
    interrupt();
    current = { utterance: line.utterance, kind: "briefing" };
    queue.push(line);
  }
  if (!speaking) next();
}

/** Stop talking now and forget anything queued. */
export function interrupt() {
  queue = [];
  current = null;
  speaking = false;
  if (speechSupported) window.speechSynthesis.cancel();
}
