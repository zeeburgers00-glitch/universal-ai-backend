import type { Config } from "tailwindcss";
const config: Config = { content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"], theme: { extend: { colors: { ink: "#0b1020", panel: "#121a2d", line: "#25324a", accent: "#9b8cff" } } }, plugins: [] };
export default config;