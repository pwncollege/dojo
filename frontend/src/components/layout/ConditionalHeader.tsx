'use client'

import { usePathname } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Header } from './Header'

export function ConditionalHeader() {
  const pathname = usePathname()

  // Check if we're in a workspace page or auth page
  const isWorkspacePage = pathname.includes('/workspace/')
  const isAuthPage = pathname.startsWith('/login') || pathname.startsWith('/register') || pathname.startsWith('/forgot-password')

  return (
    <>
      {!isWorkspacePage && !isAuthPage && <Header />}
    </>
  )
}