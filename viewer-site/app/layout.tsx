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
    default: "VerbaRadar",
    template: "%s · VerbaRadar",
  },
  description: "Live translation with evidence-linked decisions: preserve, translate, verify, and act.",
  openGraph: {
    title: "VerbaRadar",
    description: "Live translation with evidence-linked decisions.",
    type: "website",
    images: [
      {
        url: "/og-verbaradar.jpg",
        width: 1536,
        height: 1024,
        alt: "VerbaRadar live captions and evidence-linked Decision Radar",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "VerbaRadar",
    description: "Preserve the original. Translate live. Verify every decision.",
    images: ["/og-verbaradar.jpg"],
  },
  icons: {
    icon: "/verbaradar-icon.png",
    shortcut: "/verbaradar-icon.png",
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
