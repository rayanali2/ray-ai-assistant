import { expect, it, vi } from "vitest";
import { subscribeDesktopListen } from "./desktop";

it("does nothing in a normal browser", () => {
  const callback = vi.fn();
  subscribeDesktopListen(undefined, callback)();
  expect(callback).not.toHaveBeenCalled();
});

it("subscribes the mic action and cleans up the Electron listener", () => {
  const callback = vi.fn();
  const unsubscribe = vi.fn();
  const onListen = vi.fn((listener: () => void) => { listener(); return unsubscribe; });
  const cleanup = subscribeDesktopListen({ onListen }, callback);
  expect(callback).toHaveBeenCalledOnce();
  cleanup();
  expect(unsubscribe).toHaveBeenCalledOnce();
});
