import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dragon World — AI World Engine",
  description: "Persistent world state visualization for Dragon World.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
