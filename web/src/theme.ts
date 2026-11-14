import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
const key = "firelens-theme";
const eventName = "firelens-theme-change";
function snapshot(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}
function subscribe(listener: () => void) {
  function onStorage(event: StorageEvent) {
    if (event.key === key || event.key === null) {
      document.documentElement.dataset.theme =
        event.newValue === "light" ? "light" : "dark";
      listener();
    }
  }
  window.addEventListener(eventName, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(eventName, listener);
    window.removeEventListener("storage", onStorage);
  };
}
export function setTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(key, theme);
  } catch {
    /* Theme still works when storage is unavailable. */
  }
  window.dispatchEvent(new Event(eventName));
}
export function useTheme() {
  return useSyncExternalStore(subscribe, snapshot, () => "dark" as Theme);
}
export function chartColors(theme: Theme) {
  return theme === "light"
    ? {
        text: "#50657a",
        grid: "#e0e8ef",
        point: "#287eae",
        pointLine: "#ffffff",
        target: "#a16a13",
        targetFill: "rgba(187,133,39,0.075)",
        hover: "#ffffff",
        outcomes: ["#247dad", "#17846d", "#7a59b1", "#a46a1d", "#738391"],
      }
    : {
        text: "#a5bbcd",
        grid: "#263746",
        point: "#7bc4ec",
        pointLine: "#12202c",
        target: "#edc17f",
        targetFill: "rgba(237,193,127,0.06)",
        hover: "#172735",
        outcomes: ["#79cfff", "#76d9ba", "#b7a4ed", "#e8b574", "#91a3b4"],
      };
}
