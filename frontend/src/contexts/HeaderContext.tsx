import React, { createContext, useContext, useState, useEffect } from 'react'

interface HeaderContextType {
  isHeaderHidden: boolean
  setHeaderHidden: (hidden: boolean) => void
  headerHeight: number
}

const HeaderContext = createContext<HeaderContextType | undefined>(undefined)

export function HeaderProvider({ children }: { children: React.ReactNode }) {
  const [isHeaderHidden, setIsHeaderHidden] = useState(false)
  const headerHeight = 64 // 4rem / 16px

  const setHeaderHidden = (hidden: boolean) => {
    setIsHeaderHidden(hidden)
  }

  return (
    <HeaderContext.Provider value={{ isHeaderHidden, setHeaderHidden, headerHeight }}>
      {children}
    </HeaderContext.Provider>
  )
}

export function useHeader() {
  const context = useContext(HeaderContext)
  if (context === undefined) {
    throw new Error('useHeader must be used within a HeaderProvider')
  }
  return context
}