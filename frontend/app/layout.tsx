import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DRAGON WORLD — AI 世界引擎",
  description: "Dragon World 持久世界状态可视化界面。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
