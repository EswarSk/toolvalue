import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'ToolValue — Agent Tool Value Profiler',
  description: 'Know which agent tools improve quality, and which only add cost.',
  openGraph: {
    title: 'ToolValue — Agent Tool Value Profiler',
    description: 'Know which agent tools improve quality, and which only add cost.',
    type: 'website',
    images: [{ url: '/og.png', width: 1792, height: 938, alt: 'ToolValue — Know what actually helps.' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'ToolValue — Agent Tool Value Profiler',
    description: 'Know which agent tools improve quality, and which only add cost.',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body></html>;
}
