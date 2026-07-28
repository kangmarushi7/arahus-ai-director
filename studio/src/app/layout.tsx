import type { Metadata } from "next";
import { Figtree, Newsreader } from "next/font/google";

import { QueryProvider } from "@/providers/query-provider";

import "./globals.css";

const figtree = Figtree({
  subsets: ["latin"],
  variable: "--font-figtree",
});

const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
});

export const metadata: Metadata = {
  title: "Arahus Studio",
  description: "Cinematic planning and media studio for Arahus AI Director",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${figtree.variable} ${newsreader.variable} min-h-screen antialiased`}
      >
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
