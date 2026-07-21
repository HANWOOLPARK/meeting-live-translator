import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "WhyKaigi",
    template: "%s · WhyKaigi",
  },
  description: "Live translation with evidence-linked decisions: preserve, translate, verify, and act.",
  openGraph: {
    title: "WhyKaigi",
    description: "Live translation with evidence-linked decisions.",
    type: "website",
    images: [
      {
        url: "/og-whykaigi.jpg",
        width: 1536,
        height: 1024,
        alt: "WhyKaigi live captions and evidence-linked Decision Radar",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "WhyKaigi",
    description: "Preserve the original. Translate live. Verify every decision.",
    images: ["/og-whykaigi.jpg"],
  },
  icons: {
    icon: "/whykaigi-icon.png",
    shortcut: "/whykaigi-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
