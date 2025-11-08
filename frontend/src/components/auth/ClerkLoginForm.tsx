'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/stores'
import { type LoginCredentials } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Logo } from '@/components/ui/Logo'
import { Eye, EyeOff, ArrowLeft } from 'lucide-react'

export function ClerkLoginForm() {
  const router = useRouter()
  const { login, loginLoading, authError, clearError } = useAuthStore()
  const [formData, setFormData] = useState<LoginCredentials>({
    name: '',
    password: '',
    remember_me: false
  })
  const [showPassword, setShowPassword] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()

    try {
      await login(formData)
      router.push('/')
    } catch (err) {
      // Error is handled by the store
    }
  }

  const handleInputChange = (field: keyof LoginCredentials) => (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    setFormData(prev => ({
      ...prev,
      [field]: e.target.value
    }))
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="text-center space-y-6">
          <div className="flex justify-center mb-4">
            <Logo textClassName="text-3xl" />
          </div>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-foreground">Sign in to your account</h1>
            <p className="text-sm text-muted-foreground">Welcome back! Please enter your details.</p>
          </div>
        </div>

        {/* Main Form Card */}
        <Card className="shadow-lg">
          <CardContent className="p-8">
            <form onSubmit={handleSubmit} className="space-y-6">
              {authError && (
                <Alert variant="destructive">
                  <AlertDescription>{authError}</AlertDescription>
                </Alert>
              )}

              {/* Email/Username Field */}
              <div className="space-y-2">
                <Label htmlFor="name" className="text-sm font-medium">
                  Email address or username
                </Label>
                <Input
                  id="name"
                  type="text"
                  value={formData.name}
                  onChange={handleInputChange('name')}
                  placeholder="Enter your email or username"
                  required
                  disabled={loginLoading}
                  className="h-11"
                />
              </div>

              {/* Password Field */}
              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm font-medium">
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={formData.password}
                    onChange={handleInputChange('password')}
                    placeholder="Enter your password"
                    required
                    disabled={loginLoading}
                    className="h-11 pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    disabled={loginLoading}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {/* Forgot Password Link */}
              <div className="flex justify-end">
                <Link
                  href="/forgot-password"
                  className="text-sm font-medium text-primary hover:text-primary/80 transition-colors"
                >
                  Forgot your password?
                </Link>
              </div>

              {/* Submit Button */}
              <Button
                type="submit"
                className="w-full h-11 font-medium transition-colors"
                disabled={loginLoading}
              >
                {loginLoading ? (
                  <div className="flex items-center space-x-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    <span>Signing in...</span>
                  </div>
                ) : (
                  'Sign in'
                )}
              </Button>

              {/* Divider */}
              <div className="relative">
                <Separator />
                <div className="absolute inset-0 flex justify-center">
                  <span className="bg-background px-2 text-xs text-muted-foreground">or</span>
                </div>
              </div>

              {/* Sign Up Link */}
              <div className="text-center">
                <span className="text-sm text-muted-foreground">Don't have an account? </span>
                <Link
                  href="/register"
                  className="text-sm font-medium text-primary hover:text-primary/80 transition-colors"
                >
                  Sign up
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