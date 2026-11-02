import { describe, expect, it } from "vitest";
import { canUseLocalVoice, greeting, smoothLevel } from "./hud";

describe("HUD greeting", () => {
  it.each([[0, "morning"], [11, "morning"], [12, "afternoon"], [17, "afternoon"], [18, "evening"], [23, "evening"]])("greets at %i", (hour, period) => {
    expect(greeting(Number(hour), "Rayan")).toBe(`Good ${period}, Rayan.`);
  });
  it("handles an empty name", () => expect(greeting(9, " ")).toBe("Good morning, there."));
});

describe("audio envelope", () => {
  it("attacks faster than it releases", () => {
    expect(smoothLevel(0, 1)).toBe(.45);
    expect(smoothLevel(1, 0)).toBe(.88);
  });
  it("clamps invalid, excessive and silent input", () => {
    expect(smoothLevel(0, Infinity)).toBe(0);
    expect(smoothLevel(0, NaN)).toBe(0);
    expect(smoothLevel(0, -1)).toBe(0);
    expect(smoothLevel(0, 3)).toBe(.45);
    expect(smoothLevel(0, 0)).toBe(0);
  });
});

describe("local voice without SpeechRecognition", () => {
  it("needs only a ready backend, recorder and microphone", () => {
    expect(canUseLocalVoice(true, true, true)).toBe(true);
  });
  it.each([[false, true, true], [true, false, true], [true, true, false]])("rejects missing capabilities", (ready, recorder, mic) => {
    expect(canUseLocalVoice(ready, recorder, mic)).toBe(false);
  });
});
