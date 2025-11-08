'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { type RegisterData } from '@/services/auth'
import { useAuthStore } from '@/stores'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { CountrySelector } from '@/components/ui/country-selector'
import { Logo } from '@/components/ui/Logo'
import { Eye, EyeOff, ArrowLeft, Check, X } from 'lucide-react'

const PASSWORD_MIN_LENGTH = 8

type PasswordChecks = {
  length: boolean
  uppercase: boolean
  lowercase: boolean
  number: boolean
}

function validatePassword(password: string): PasswordChecks {
  return {
    length: password.length >= PASSWORD_MIN_LENGTH,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    number: /\d/.test(password)
  }
}

function isPasswordValid(checks: PasswordChecks): boolean {
  return checks.length && checks.uppercase && checks.lowercase && checks.number
}

const PASSWORD_REQUIREMENTS = [
  { key: 'length' as const, label: `At least ${PASSWORD_MIN_LENGTH} characters` },
  { key: 'uppercase' as const, label: 'One uppercase letter' },
  { key: 'lowercase' as const, label: 'One lowercase letter' },
  { key: 'number' as const, label: 'One number' }
]

export function ClerkSignupForm() {
  const router = useRouter()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [affiliation, setAffiliation] = useState('')
  const [country, setCountry] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const passwordChecks = password ? validatePassword(password) : null
  const canSubmit = !!(name && email && password && passwordChecks && isPasswordValid(passwordChecks))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (loading) return

    setLoading(true)
    setError(null)

    try {
      const data: RegisterData = { name, email, password }
      if (affiliation.trim()) data.affiliation = affiliation.trim()
      if (country.trim()) data.country = country.trim()

      await useAuthStore.getState().register(data)
      router.push('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-8">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-6">
          <div className="flex justify-center mb-4">
            <Logo textClassName="text-3xl" />
          </div>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-foreground">Create your account</h1>
            <p className="text-sm text-muted-foreground">Welcome! Please fill in the details to get started.</p>
          </div>
        </div>

        <Card className="border-0 shadow-lg">
          <CardContent className="p-8">
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="name" className="text-sm font-medium">
                  Username
                </Label>
                <Input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value)
                    if (error) setError(null)
                  }}
                  placeholder="Choose a username"
                  required
                  disabled={loading}
                  className="h-11"
                  autoComplete="username"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="email" className="text-sm font-medium">
                  Email address
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    if (error) setError(null)
                  }}
                  placeholder="Enter your email"
                  required
                  disabled={loading}
                  className="h-11"
                  autoComplete="email"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm font-medium">
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value)
                      if (error) setError(null)
                    }}
                    placeholder="Create a password"
                    required
                    disabled={loading}
                    className="h-11 pr-10"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    disabled={loading}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>

                {passwordChecks && (
                  <div className="space-y-2 mt-3 p-3 bg-muted/30 rounded-md">
                    <p className="text-xs font-medium text-foreground">Password must contain:</p>
                    <div className="space-y-1">
                      {PASSWORD_REQUIREMENTS.map(({ key, label }) => {
                        const met = passwordChecks[key]
                        return (
                          <div key={key} className="flex items-center space-x-2 text-xs">
                            {met ? (
                              <Check className="h-3 w-3 text-green-500 shrink-0" />
                            ) : (
                              <X className="h-3 w-3 text-muted-foreground shrink-0" />
                            )}
                            <span className={met ? 'text-green-700' : 'text-muted-foreground'}>
                              {label}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="affiliation" className="text-sm font-medium">
                    Affiliation <span className="text-muted-foreground">(optional)</span>
                  </Label>
                  <Input
                    id="affiliation"
                    type="text"
                    value={affiliation}
                    onChange={(e) => setAffiliation(e.target.value)}
                    placeholder="Company/School"
                    disabled={loading}
                    className="h-11"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-sm font-medium">
                    Country <span className="text-muted-foreground">(optional)</span>
                  </Label>
                  <CountrySelector
                    value={country}
                    onValueChange={setCountry}
                    placeholder="Search or select country"
                    disabled={loading}
                    className="h-11"
                  />
                </div>
              </div>

              <Button
                type="submit"
                className="w-full h-11 font-medium"
                disabled={loading || !canSubmit}
              >
                {loading ? (
                  <div className="flex items-center space-x-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    <span>Creating account...</span>
                  </div>
                ) : (
                  'Create account'
                )}
              </Button>

              <p className="text-xs text-center text-muted-foreground leading-relaxed">
                By clicking "Create account", you agree to our{' '}
                <Link href="/terms" className="text-primary hover:text-primary/80 transition-colors">
                  Terms of Service
                </Link>{' '}
                and{' '}
                <Link href="/privacy" className="text-primary hover:text-primary/80 transition-colors">
                  Privacy Policy
                </Link>
                .
              </p>

              <div className="relative">
                <Separator />
                <div className="absolute inset-0 flex justify-center">
                  <span className="bg-background px-2 text-xs text-muted-foreground">or</span>
                </div>
              </div>

              <div className="text-center">
                <span className="text-sm text-muted-foreground">Already have an account? </span>
                <Link
                  href="/login"
                  className="text-sm font-medium text-primary hover:text-primary/80 transition-colors"
                >
                  Sign in
                </Link>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="text-center">
          <Link
            href="/"
            className="inline-flex items-center space-x-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Back to pwn.college</span>
          </Link>
        </div>
      </div>
    </div>
  )
}
