import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CiaNet Panel",
  description: "Telegram Selfbot Management Panel",
};

export default function RootLayout({
  children,
}: { children: React.ReactNode }) {
  return (
    <html lang="fa" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
