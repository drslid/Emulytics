import type { CSSProperties } from "react";

const paths = {
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M17 4a4 4 0 0 1 0 7 M22 21v-2a4 4 0 0 0-3-4",
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  phone: "M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z M10 18h4",
  workflow: "M4 4h6v6H4z M14 14h6v6h-6z M10 7h7v7 M7 10v7h7",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  shield: "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3z M9 12l2 2 4-4",
  plus: "M12 5v14 M5 12h14",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  close: "M6 6l12 12 M6 18 18 6",
  search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z M16 16l5 5",
  refresh: "M20 8a8 8 0 1 0 0 8 M20 3v5h-5",
  logout: "M9 4H4v16h5 M9 12h12 M17 8l4 4-4 4",
  check: "M5 12l4 4L19 6",
  warning: "M12 3 2 21h20L12 3z M12 9v5 M12 17v1",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  play: "M8 4v16l12-8L8 4z",
  power: "M12 2v10 M5.6 5.6a9 9 0 1 0 12.8 0",
  settings: "M9.13 5.07 L10.26 2.15 L13.74 2.15 L14.87 5.07 L17.74 3.81 L20.19 6.26 L18.93 9.13 L21.85 10.26 L21.85 13.74 L18.93 14.87 L20.19 17.74 L17.74 20.19 L14.87 18.93 L13.74 21.85 L10.26 21.85 L9.13 18.93 L6.26 20.19 L3.81 17.74 L5.07 14.87 L2.15 13.74 L2.15 10.26 L5.07 9.13 L3.81 6.26 L6.26 3.81 L9.13 5.07z M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z",
  archive: "M3 4h18v5H3z M5 9v11h14V9 M9 13h6",
  key: "M9 15a6 6 0 1 1 4-10 6 6 0 0 1 0 8l8 0v4h-4v3h-4v-5H9z"
};
export function Icon({ name, size = 20, style }: { name: keyof typeof paths; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" data-directional={name === "arrow" || name === "logout" ? "true" : undefined} style={style}><path d={paths[name]} /></svg>;
}
