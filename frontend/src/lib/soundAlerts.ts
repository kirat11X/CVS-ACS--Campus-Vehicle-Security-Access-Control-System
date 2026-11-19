import { useCallback, useState } from "react";

/**
 * Web Audio API synthesized sound generator for CVS-ACS alerts.
 * Uses native AudioContext oscillators so it works 100% offline with zero
 * external media assets or network latency.
 */

class SoundAlertController {
  private ctx: AudioContext | null = null;
  private enabled: boolean = true;

  constructor() {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("cvs_alert_sound_enabled");
      this.enabled = saved !== "false";
    }
  }

  public isEnabled(): boolean {
    return this.enabled;
  }

  public setEnabled(value: boolean) {
    this.enabled = value;
    if (typeof window !== "undefined") {
      localStorage.setItem("cvs_alert_sound_enabled", String(value));
    }
    if (value) {
      this.playTestSound();
    }
  }

  public init(): AudioContext | null {
    if (typeof window === "undefined") return null;
    try {
      if (!this.ctx) {
        const AudioCtx =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        if (AudioCtx) {
          this.ctx = new AudioCtx();
        }
      }
      if (this.ctx && this.ctx.state === "suspended") {
        this.ctx.resume().catch(() => {});
      }
    } catch (e) {
      console.warn("AudioContext init error:", e);
    }
    return this.ctx;
  }

  /**
   * Plays an urgent audio alarm for HIGH severity contraband/security alerts.
   * Distinctive 4-tone urgent siren (880Hz <-> 1174Hz).
   */
  public playHighAlertSound() {
    if (!this.enabled) return;
    const ctx = this.init();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.connect(gain);
      gain.connect(ctx.destination);

      // Rapid urgent 4-pulse chime: 880Hz -> 1174Hz -> 880Hz -> 1174Hz
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.setValueAtTime(1174, now + 0.12);
      osc.frequency.setValueAtTime(880, now + 0.24);
      osc.frequency.setValueAtTime(1174, now + 0.36);

      gain.gain.setValueAtTime(0.3, now);
      gain.gain.setValueAtTime(0.3, now + 0.45);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.65);

      osc.start(now);
      osc.stop(now + 0.65);
    } catch (e) {
      console.warn("Failed to play high alert sound:", e);
    }
  }

  /**
   * Plays an advisory warning chime for MEDIUM severity alerts / review items.
   * Two-tone prompt chime (659Hz -> 880Hz).
   */
  public playMediumAlertSound() {
    if (!this.enabled) return;
    const ctx = this.init();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "triangle";
      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.frequency.setValueAtTime(659, now);
      osc.frequency.setValueAtTime(880, now + 0.14);

      gain.gain.setValueAtTime(0.22, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.42);

      osc.start(now);
      osc.stop(now + 0.42);
    } catch (e) {
      console.warn("Failed to play medium alert sound:", e);
    }
  }

  /**
   * Friendly 3-tone ascending chime (C5 -> E5 -> G5) to test audio speaker.
   */
  public playTestSound() {
    const ctx = this.init();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.frequency.setValueAtTime(523.25, now);        // C5
      osc.frequency.setValueAtTime(659.25, now + 0.10); // E5
      osc.frequency.setValueAtTime(783.99, now + 0.20); // G5

      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.50);

      osc.start(now);
      osc.stop(now + 0.50);
    } catch (e) {
      console.warn("Failed to play test sound:", e);
    }
  }
}

export const soundAlerts = new SoundAlertController();

/**
 * React hook providing reactive sound enabled status and controls.
 */
export function useSoundAlerts() {
  const [enabled, setEnabledState] = useState<boolean>(() => soundAlerts.isEnabled());

  const toggleSound = useCallback(() => {
    soundAlerts.init();
    const next = !soundAlerts.isEnabled();
    soundAlerts.setEnabled(next);
    setEnabledState(next);
  }, []);

  const testSound = useCallback(() => {
    soundAlerts.init();
    soundAlerts.playTestSound();
  }, []);

  const playHighAlert = useCallback(() => {
    soundAlerts.playHighAlertSound();
  }, []);

  const playMediumAlert = useCallback(() => {
    soundAlerts.playMediumAlertSound();
  }, []);

  return {
    soundEnabled: enabled,
    toggleSound,
    testSound,
    playHighAlert,
    playMediumAlert,
  };
}
