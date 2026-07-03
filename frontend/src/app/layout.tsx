import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Research Paper Assistant — Evidence-Based Writing',
  description:
    'Upload your literature and project files to generate a fully cited research paper. Every sentence is traceable to its source.',
  keywords: ['research paper', 'citation', 'evidence-based', 'academic writing', 'AI assistant'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>{children}</body>
    </html>
  );
}
