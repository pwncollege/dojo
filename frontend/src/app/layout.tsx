import type { Metadata } from 'next'
import '../index.css'
import { Providers } from './providers'
import { generateThemeScript } from '@/lib/generate-theme-script'

export const metadata: Metadata = {
  title: 'pwn.college DOJO',
  description: 'Cybersecurity education platform',
  icons: {
    icon: '/favicon.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const themeScript = generateThemeScript()

  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <script
          dangerouslySetInnerHTML={{
            __html: themeScript
          }}
        />
        <div className="min-h-screen bg-background text-foreground">
          <Providers>
            {children}
          </Providers>
        </div>
      </body>
    </html>
  )
}