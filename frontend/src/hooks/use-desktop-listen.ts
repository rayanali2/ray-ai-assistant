"use client";

import { useEffect } from "react";
import { subscribeDesktopListen, type DesktopBridge } from "@/lib/desktop";

export function useDesktopListen(onListen: () => void) {
  useEffect(() => {
    const bridge = (window as Window & { rayDesktop?: DesktopBridge }).rayDesktop;
    return subscribeDesktopListen(bridge, onListen);
  }, [onListen]);
}
