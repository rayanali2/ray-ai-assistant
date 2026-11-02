export interface DesktopBridge {
  onListen(callback: () => void): () => void;
}

export function subscribeDesktopListen(bridge: DesktopBridge | undefined, callback: () => void): () => void {
  return bridge?.onListen(callback) ?? (() => {});
}
