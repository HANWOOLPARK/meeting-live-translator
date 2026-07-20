import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Meeting Live Translator",
    template: "%s · Meeting Live Translator",
  },
  description: "Live translation with evidence-linked decisions: preserve, translate, verify, and act.",
  openGraph: {
    title: "Meeting Live Translator",
    description: "Live translation with evidence-linked decisions.",
    type: "website",
    images: [
      {
        url: "/og-meeting-live-translator.png",
        width: 1664,
        height: 948,
        alt: "Meeting Live Translator live captions and Decision Radar",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Meeting Live Translator",
    description: "Preserve the original. Translate live. Verify every decision.",
    images: ["/og-meeting-live-translator.png"],
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
