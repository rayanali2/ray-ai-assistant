export function greeting(hour: number, name: string): string {
  const period = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  return `Good ${period}, ${name.trim() || "there"}.`;
}

export function smoothLevel(previous: number, next: number): number {
  const target = Number.isFinite(next) ? Math.max(0, Math.min(1, next)) : 0;
  return previous + (target - previous) * (target > previous ? 0.45 : 0.12);
}

export function canUseLocalVoice(ready: boolean, recorder: boolean, microphone: boolean): boolean {
  return ready && recorder && microphone;
}
