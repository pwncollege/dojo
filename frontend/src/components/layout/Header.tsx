'use client'

import Link from 'next/link'
import { usePathname, useParams } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Logo } from '@/components/ui/Logo'
import { useAuthStore, useUIStore } from '@/stores'
import {
  Menu, X, User, LogOut, Shield, ChevronRight,
  BookOpen, Trophy, Users, Settings, Search
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { ThemeSelector } from '@/components/ui/theme-selector'
import { SearchModal } from '@/components/ui/search-modal'
import { cn } from '@/lib/utils'

export function Header() {
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)
  const isLoading = useAuthStore(state => state.isLoading)
  const hasHydrated = useAuthStore(state => state.hasHydrated)
  const user = useAuthStore(state => state.user)
  const logout = useAuthStore(state => state.logout)
  const isHeaderHidden = useUIStore(state => state.isHeaderHidden)

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [searchModalOpen, setSearchModalOpen] = useState(false)
  const pathname = usePathname()
  const params = useParams()
  const dojoId = params?.dojoId as string
  const [scrolled, setScrolled] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [lastScrollY, setLastScrollY] = useState(0)

  // Handle global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+K or Cmd+K to open search
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSearchModalOpen(true)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Track scroll position for navbar styling and hide/show behavior
  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY

      setScrolled(currentScrollY > 10)

      // Hide/show logic - only affect scroll-based hiding, not HeaderContext
      if (currentScrollY > lastScrollY && currentScrollY > 100) {
        // Scrolling down and past threshold
        setHidden(true)
      } else if (currentScrollY < lastScrollY) {
        // Scrolling up
        setHidden(false)
      }

      setLastScrollY(currentScrollY)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [lastScrollY])

  // Get current dojo info if we're on a dojo page
  const currentDojo = dojoId ? null : null // TODO: Get dojo name from page context

  const handleLogout = async () => {
    await logout()
    setMobileMenuOpen(false)
  }

  // Smart navigation items based on context
  const navItems = [
    { name: 'Dojos', href: '/', icon: BookOpen, active: pathname === '/' },
    { name: 'Leaderboard', href: '/leaderboard', icon: Trophy, active: pathname === '/leaderboard' },
    { name: 'Community', href: '/community', icon: Users, active: pathname === '/community' },
  ]

  // Generate breadcrumbs based on current path
  const breadcrumbs = []
  if (pathname !== '/') {
    breadcrumbs.push({ name: 'Home', href: '/' })

    if (currentDojo) {
      breadcrumbs.push({ name: currentDojo.name, href: `/dojo/${dojoId}` })
    }
  }

  return (
    <header className={cn(
      "sticky top-0 z-50 w-full border-b transition-all duration-300",
      scrolled
        ? "border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-sm"
        : "border-border/50 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60",
      // HeaderContext hiding takes priority over scroll hiding
      isHeaderHidden ? "hidden" : (hidden ? "-translate-y-full" : "translate-y-0")
    )}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <div className="flex items-center space-x-8">
            <Logo />

            {/* Desktop Navigation */}
            <nav className="hidden lg:flex items-center space-x-1">
              {navItems.map((item) => (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    "flex items-center space-x-1.5 px-3 py-2 text-sm transition-colors",
                    item.active
                      ? "text-primary font-semibold"
                      : "text-muted-foreground hover:text-foreground font-medium"
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  <span>{item.name}</span>
                </Link>
              ))}
            </nav>
          </div>

          {/* Desktop Right Section */}
          <div className="hidden lg:flex items-center space-x-3">
            {/* Search Button */}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSearchModalOpen(true)}
              title="Search (Ctrl+K)"
              className="hover:bg-primary/10 hover:text-primary"
            >
              <Search className="h-4 w-4" />
            </Button>

            <div className="h-6 w-px bg-border" />

            <Button variant="ghost" size="icon" asChild className="hover:bg-primary/10 hover:text-primary">
              <ThemeSelector />
            </Button>
            {!hasHydrated ? (
              <div className="h-9 w-9 bg-muted animate-pulse rounded-full" />
            ) : isAuthenticated && user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="relative group h-9 px-2 hover:bg-primary/10 hover:text-primary">
                    <div className="flex items-center space-x-2">
                      <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                        <span className="text-sm font-medium text-primary">
                          {user.username?.charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div className="text-left hidden xl:block">
                        <div className="text-sm font-medium text-foreground">{user.username}</div>
                        <div className="text-xs text-muted-foreground">Level 5</div>
                      </div>
                    </div>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel className="font-normal">
                    <div className="flex flex-col space-y-1">
                      <p className="text-sm font-medium leading-none">{user.username}</p>
                      <p className="text-xs leading-none text-muted-foreground">{user.email}</p>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild className="data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary transition-colors cursor-pointer">
                    <Link href="/profile">
                      <User className="mr-2 h-4 w-4" />
                      <span>Profile</span>
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem className="data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary transition-colors cursor-pointer">
                    <Settings className="mr-2 h-4 w-4" />
                    <span>Settings</span>
                  </DropdownMenuItem>
                  {user.type === 'admin' && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem className="data-[highlighted]:bg-primary/10 data-[highlighted]:text-primary transition-colors cursor-pointer">
                        <Shield className="mr-2 h-4 w-4" />
                        <span>Admin Panel</span>
                        <Badge variant="destructive" className="ml-auto text-xs">
                          Admin
                        </Badge>
                      </DropdownMenuItem>
                    </>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={handleLogout}
                    className="text-destructive data-[highlighted]:bg-destructive/10 data-[highlighted]:text-destructive transition-colors cursor-pointer"
                  >
                    <LogOut className="mr-2 h-4 w-4" />
                    <span>Log out</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <div className="flex items-center space-x-2">
                <Button variant="ghost" size="sm" asChild>
                  <Link href="/login" className="text-sm">
                    Login
                  </Link>
                </Button>
                <Button size="sm" asChild>
                  <Link href="/register" className="text-sm">
                    Register
                  </Link>
                </Button>
              </div>
            )}
          </div>

          {/* Mobile Menu Button */}
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="lg:hidden border-t border-border bg-background">
          <div className="px-4 py-4 space-y-4">
            {/* Mobile Breadcrumbs */}
            {breadcrumbs.length > 1 && (
              <div className="pb-2 border-b border-border">
                <nav className="flex items-center space-x-1 text-xs">
                  {breadcrumbs.map((crumb, index) => (
                    <div key={crumb.href} className="flex items-center">
                      {index > 0 && <ChevronRight className="h-3 w-3 mx-1 text-muted-foreground" />}
                      <Link
                        href={crumb.href}
                        className="flex items-center space-x-1 text-muted-foreground"
                        onClick={() => setMobileMenuOpen(false)}
                      >
                        <span>{crumb.name}</span>
                      </Link>
                    </div>
                  ))}
                </nav>
              </div>
            )}

            {/* Mobile Search Button */}
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start"
              onClick={() => {
                setSearchModalOpen(true)
                setMobileMenuOpen(false)
              }}
            >
              <Search className="h-4 w-4 mr-2" />
              Search
              <Badge variant="outline" className="ml-auto text-xs">
                Ctrl+K
              </Badge>
            </Button>

            {/* Mobile Navigation */}
            <nav className="space-y-1">
              {navItems.map((item) => (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    "flex items-center space-x-2 px-3 py-2 text-sm transition-colors",
                    item.active
                      ? "text-primary font-semibold"
                      : "text-muted-foreground hover:text-foreground font-medium"
                  )}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <item.icon className="h-4 w-4" />
                  <span>{item.name}</span>
                </Link>
              ))}
            </nav>

            {/* Mobile Theme Selector */}
            <div className="pt-4 border-t border-border">
              <div className="flex justify-center">
                <ThemeSelector />
              </div>
            </div>

            {/* Mobile Auth Section */}
            <div className="pt-4 border-t border-border">
              {!hasHydrated ? (
                <div className="h-8 bg-muted animate-pulse rounded" />
              ) : isAuthenticated && user ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <div className="text-sm">
                        <div className="font-medium text-foreground">{user.username}</div>
                        <div className="text-xs text-muted-foreground">{user.email}</div>
                      </div>
                      {user.type === 'admin' && (
                        <Badge variant="destructive" className="text-xs">
                          Admin
                        </Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleLogout}
                    className="w-full justify-start"
                  >
                    <LogOut className="h-4 w-4 mr-2" />
                    Logout
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <Button variant="ghost" size="sm" className="w-full justify-start" asChild>
                    <Link href="/login" onClick={() => setMobileMenuOpen(false)}>
                      Login
                    </Link>
                  </Button>
                  <Button size="sm" className="w-full" asChild>
                    <Link href="/register" onClick={() => setMobileMenuOpen(false)}>
                      Register
                    </Link>
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Search Modal */}
      <SearchModal
        isOpen={searchModalOpen}
        onClose={() => setSearchModalOpen(false)}
      />
    </header>
  )
}
