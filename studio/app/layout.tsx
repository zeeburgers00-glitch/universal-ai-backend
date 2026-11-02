import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "AI YouTube Studio Autopilot", description: "Research, create and schedule original YouTube videos with a guarded AI production workflow." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }