import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { AppSidebar, MobileNav } from "@/components/app-sidebar";
import { Toaster } from "@/components/ui/sonner";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: {
    default: "K8s LLM Incident Analyser",
    template: "%s · K8s LLM Incident Analyser",
  },
  description:
    "LLM-powered Kubernetes pod failure analysis — live pipelines, incident reports and fault scenarios.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} font-sans antialiased`}>
        {/* Layered ambient background: radial base → noise → grid → floating light pools */}
        <div aria-hidden className="pointer-events-none fixed inset-0">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,#0a0a0f_0%,#050506_50%,#020203_100%)]" />
          <div className="bg-noise absolute inset-0 opacity-[0.015]" />
          <div className="bg-grid absolute inset-0 opacity-[0.02]" />
          <div className="absolute inset-x-0 -top-48 mx-auto h-[560px] w-[900px] rounded-full bg-accent-indigo/10 blur-[140px] motion-safe:animate-float" />
          <div className="absolute -bottom-40 -left-48 h-[480px] w-[640px] rounded-full bg-[#7a5ed2]/[0.07] blur-[120px] motion-safe:animate-float-slow" />
        </div>
        <div className="relative min-h-screen">
          <AppSidebar />
          <div className="flex min-h-screen min-w-0 flex-col md:pl-64">
            <MobileNav />
            <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 md:px-8">
              <div className="page-enter">{children}</div>
            </main>
          </div>
        </div>
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
