'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { authService, type RegisterData } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { CountrySelector } from '@/components/ui/country-selector'
import { Logo } from '@/components/ui/Logo'
import { Eye, EyeOff, ArrowLeft, Check, X } from 'lucide-react'

interface PasswordRequirement {
  met: boolean
  text: string
}

export function ClerkSignupForm() {
  const router = useRouter()
  const [formData, setFormData] = useState<RegisterData>({
    name: '',
    email: '',
    password: '',
    affiliation: '',
    country: ''
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)

  const passwordRequirements: PasswordRequirement[] = [
    { met: formData.password.length >= 8, text: 'At least 8 characters' },
    { met: /[A-Z]/.test(formData.password), text: 'One uppercase letter' },
    { met: /[a-z]/.test(formData.password), text: 'One lowercase letter' },
    { met: /\d/.test(formData.password), text: 'One number' }
  ]

  const isPasswordValid = passwordRequirements.every(req => req.met)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!isPasswordValid) {
      setError('Please meet all password requirements')
      return
    }

    setLoading(true)
    setError(null)

    try {
      // Clean up the form data - remove empty/null optional fields
      const cleanFormData: RegisterData = {
        name: formData.name,
        email: formData.email,
        password: formData.password
      }

      // Only include optional fields if they have actual values
      if (formData.affiliation && formData.affiliation.trim() !== '') {
        cleanFormData.affiliation = formData.affiliation.trim()
      }

      if (formData.country && formData.country.trim() !== '') {
        cleanFormData.country = formData.country.trim()
      }

      const response = await authService.register(cleanFormData)

      if (response.success) {
        router.push('/')
      } else {
        setError(response.errors?.join(', ') || 'Registration failed')
      }
    } catch (err: any) {
      setError(err.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }

  const handleInputChange = (field: keyof RegisterData) => (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    setFormData(prev => ({
      ...prev,
      [field]: e.target.value
    }))
  }

  const handleCountryChange = (value: string) => {
    setFormData(prev => ({
      ...prev,
      country: value
    }))
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-8">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="text-center space-y-6">
          <div className="flex justify-center mb-4">
            <Logo textClassName="text-3xl" />
          </div>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-foreground">Create your account</h1>
            <p className="text-sm text-muted-foreground">Welcome! Please fill in the details to get started.</p>
          </div>
        </div>

        {/* Main Form Card */}
        <Card className="border-0 shadow-lg">
          <CardContent className="p-8">
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {/* Username Field */}
              <div className="space-y-2">
                <Label htmlFor="name" className="text-sm font-medium ">
                  Username
                </Label>
                <Input
                  id="name"
                  type="text"
                  value={formData.name}
                  onChange={handleInputChange('name')}
                  placeholder="Choose a username"
                  required
                  disabled={loading}
                  className="h-11 "
                />
              </div>

              {/* Email Field */}
              <div className="space-y-2">
                <Label htmlFor="email" className="text-sm font-medium ">
                  Email address
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={formData.email}
                  onChange={handleInputChange('email')}
                  placeholder="Enter your email"
                  required
                  disabled={loading}
                  className="h-11 "
                />
              </div>

              {/* Password Field */}
              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm font-medium ">
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={formData.password}
                    onChange={handleInputChange('password')}
                    placeholder="Create a password"
                    required
                    disabled={loading}
                    className="h-11 pr-10 "
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    disabled={loading}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>

                {/* Password Requirements */}
                {formData.password && (
                  <div className="space-y-2 mt-3 p-3 bg-muted/30 rounded-md">
                    <p className="text-xs font-medium text-foreground">Password must contain:</p>
                    <div className="space-y-1">
                      {passwordRequirements.map((req, index) => (
                        <div key={index} className="flex items-center space-x-2 text-xs">
                          {req.met ? (
                            <Check className="h-3 w-3 text-green-500" />
                          ) : (
                            <X className="h-3 w-3 text-muted-foreground" />
                          )}
                          <span className={req.met ? 'text-green-700' : 'text-muted-foreground'}>
                            {req.text}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Optional Fields */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="affiliation" className="text-sm font-medium">
                    Affiliation <span className="text-muted-foreground">(optional)</span>
                  </Label>
                  <Input
                    id="affiliation"
                    type="text"
                    value={formData.affiliation}
                    onChange={handleInputChange('affiliation')}
                    placeholder="Company/School"
                    disabled={loading}
                    className="h-11 "
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-sm font-medium">
                    Country <span className="text-muted-foreground">(optional)</span>
                  </Label>
                  <CountrySelector
                    value={formData.country}
                    onValueChange={handleCountryChange}
                    placeholder="Select country"
                    disabled={loading}
                    className="h-11"
                  />
                </div>
              </div>

              {/* Submit Button */}
              <Button
                type="submit"
                className="w-full h-11 font-medium transition-colors"
                disabled={loading || !isPasswordValid}
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

              {/* Terms */}
              <p className="text-xs text-center text-muted-foreground leading-relaxed">
                By clicking "Create account", you agree to our{' '}
                <Link href="/terms" className="text-primary hover:text-primary/80">
                  Terms of Service
                </Link>{' '}
                and{' '}
                <Link href="/privacy" className="text-primary hover:text-primary/80">
                  Privacy Policy
                </Link>
                .
              </p>

              {/* Divider */}
              <div className="relative">
                <Separator />
                <div className="absolute inset-0 flex justify-center">
                  <span className="bg-background px-2 text-xs text-muted-foreground">or</span>
                </div>
              </div>

              {/* Sign In Link */}
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

        {/* Back to Home */}
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