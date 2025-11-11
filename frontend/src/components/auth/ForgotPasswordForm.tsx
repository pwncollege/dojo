'use client'

import { useState } from 'react'
import Link from 'next/link'
import { authService } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Logo } from '@/components/ui/Logo'
import { ArrowLeft, Mail, CheckCircle } from 'lucide-react'

export function ForgotPasswordForm() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const response = await authService.forgotPassword(email)

      if (response.success) {
        setSuccess(true)
      } else {
        // Handle both errors array and message
        const errorMessage = response.errors?.join(', ') || response.message || 'Failed to send reset email'
        setError(errorMessage)
      }
    } catch (err: any) {
      setError(err.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="w-full max-w-md space-y-6">
          {/* Header */}
          <div className="text-center space-y-6">
            <div className="flex justify-center mb-4">
              <Logo textClassName="text-3xl" />
            </div>
          </div>

          {/* Success Card */}
          <Card className="border-0 shadow-lg">
            <CardContent className="p-8 text-center space-y-6">
              <div className="flex justify-center">
                <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
                  <CheckCircle className="h-8 w-8 text-green-600" />
                </div>
              </div>

              <div className="space-y-2">
                <h1 className="text-xl font-semibold text-foreground">Check your email</h1>
                <p className="text-sm text-muted-foreground">
                  We've sent a password reset link to{' '}
                  <span className="font-medium text-foreground">{email}</span>
                </p>
              </div>

              <div className="space-y-4">
                <Button
                  onClick={() => setSuccess(false)}
                  variant="outline"
                  className="w-full"
                >
                  Try another email
                </Button>

                <Link href="/login">
                  <Button className="w-full">
                    Back to sign in
                  </Button>
                </Link>
              </div>

              <div className="pt-4 text-xs text-muted-foreground space-y-1">
                <p>Didn't receive the email? Check your spam folder.</p>
                <p>
                  The reset link will expire in 24 hours for security reasons.
                </p>
              </div>
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

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="text-center space-y-6">
          <div className="flex justify-center mb-4">
            <Logo textClassName="text-3xl" />
          </div>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-foreground">Forgot your password?</h1>
            <p className="text-sm text-muted-foreground">
              No worries! Enter your email and we'll send you a reset link.
            </p>
          </div>
        </div>

        {/* Main Form Card */}
        <Card className="border-0 shadow-lg">
          <CardContent className="p-8">
            <form onSubmit={handleSubmit} className="space-y-6">
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {/* Email Field */}
              <div className="space-y-2">
                <Label htmlFor="email" className="text-sm font-medium">
                  Email address
                </Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Enter your email address"
                    required
                    disabled={loading}
                    className="h-11 pl-10"
                  />
                </div>
              </div>

              {/* Submit Button */}
              <Button
                type="submit"
                className="w-full h-11 font-medium transition-colors"
                disabled={loading}
              >
                {loading ? (
                  <div className="flex items-center space-x-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    <span>Sending reset link...</span>
                  </div>
                ) : (
                  'Send reset link'
                )}
              </Button>

              {/* Back to Login */}
              <div className="text-center">
                <Link
                  href="/login"
                  className="text-sm font-medium text-primary hover:text-primary/80 transition-colors"
                >
                  ← Back to sign in
                </Link>
              </div>
            </form>
          </CardContent>
        </Card>

        {/* Security Note */}
        <div className="text-center">
          <p className="text-xs text-muted-foreground max-w-sm mx-auto leading-relaxed">
            For security reasons, we'll send the reset link to the email associated with your account.
            If you don't have access to that email, please contact support.
          </p>
        </div>

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