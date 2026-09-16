/**
 * Native Android Haptic Feedback & Vibrations.
 * Uses Web Vibration API and Capacitor Haptics if available.
 */

export function hapticLight(): void {
  try {
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      navigator.vibrate(8);
    }
  } catch {
    /* ignore if unsupported */
  }
}

export function hapticMedium(): void {
  try {
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      navigator.vibrate(16);
    }
  } catch {
    /* ignore */
  }
}

export function hapticSuccess(): void {
  try {
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      navigator.vibrate([10, 40, 12]);
    }
  } catch {
    /* ignore */
  }
}

export function hapticError(): void {
  try {
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      navigator.vibrate([30, 40, 30]);
    }
  } catch {
    /* ignore */
  }
}
