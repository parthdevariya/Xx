import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter_Tight, Space_Grotesk } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

const ui = Inter_Tight({ variable: "--font-ui", subsets: ["latin"], display: "swap" });
const display = Space_Grotesk({ variable: "--font-display-face", subsets: ["latin"], weight: ["400", "500", "600", "700"], display: "swap" });
const code = IBM_Plex_Mono({ variable: "--font-code", subsets: ["latin"], weight: ["400", "500"], display: "swap" });

export const metadata: Metadata = {
  title: "X — Computational Intelligence",
  description: "AI, Quantum and the X Intellect framework working together on real problems.",
};

export const viewport: Viewport = { themeColor: "#050708", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${ui.variable} ${display.variable} ${code.variable}`}>
      <body className="antialiased">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-green focus:px-3 focus:py-1.5 focus:text-black">
          Skip to content
        </a>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
