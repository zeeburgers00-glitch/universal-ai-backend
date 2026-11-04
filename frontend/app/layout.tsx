import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Universal AI Empire — Command Centre",
  description: "A private command centre for the Universal AI earning system.",
  applicationName: "Universal AI Empire"
};

export const viewport: Viewport = {
  themeColor: "#071013",
  colorScheme: "dark"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
