/** Auto-translate wrapper: instructs the agent to reply in the target language. */

export function wrapTranslate(text: string, enabled: boolean, target: "en" | "hi"): string {
  if (!enabled || text.startsWith("[Reply ONLY")) return text;
  return target === "en"
    ? `[Reply ONLY in English. The user message below may be in Hindi/Hinglish — understand it, then answer in English.]\n\nUser: ${text}`
    : `[Reply ONLY in Hindi (Devanagari script). The user message below may be in English — understand it, then answer in Hindi.]\n\nUser: ${text}`;
}

export function containsDevanagari(text: string): boolean {
  return /[\u0900-\u097F]/.test(text);
}
