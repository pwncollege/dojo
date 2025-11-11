import { useState } from 'react'
import { authService, type LoginCredentials } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'

interface LoginFormProps {
  onSuccess?: () => void
  onRegisterClick?: () => void
  onForgotPasswordClick?: () => void
}

export function LoginForm({ onSuccess, onRegisterClick, onForgotPasswordClick }: LoginFormProps) {
  const [formData, setFormData] = useState<LoginCredentials>({
    name: '',
    password: '',
    remember_me: false
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const response = await authService.login(formData)

      if (response.success) {
        onSuccess?.()
      } else {
        setError(response.errors?.join(', ') || 'Login failed')
      }
    } catch (err: any) {
      setError(err.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }

  const handleInputChange = (field: keyof LoginCredentials) => (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    setFormData(prev => ({
      ...prev,
      [field]: e.target.type === 'checkbox' ? e.target.checked : e.target.value
    }))
  }

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle>Sign In</CardTitle>
        <CardDescription>
          Enter your credentials to access your account
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="name">Username or Email</Label>
            <Input
              id="name"
              type="text"
              value={formData.name}
              onChange={handleInputChange('name')}
              placeholder="Enter your username or email"
              required
              disabled={loading}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              value={formData.password}
              onChange={handleInputChange('password')}
              placeholder="Enter your password"
              required
              disabled={loading}
            />
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox
              id="remember_me"
              checked={formData.remember_me}
              onCheckedChange={(checked: boolean) =>
                setFormData(prev => ({ ...prev, remember_me: !!checked }))
              }
              disabled={loading}
            />
            <Label htmlFor="remember_me" className="text-sm">
              Remember me
            </Label>
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </Button>

          <div className="text-center space-y-2">
            {onForgotPasswordClick && (
              <button
                type="button"
                onClick={onForgotPasswordClick}
                className="text-sm text-blue-600 hover:underline"
                disabled={loading}
              >
                Forgot your password?
              </button>
            )}

            {onRegisterClick && (
              <div className="text-sm text-gray-600">
                Don't have an account?{' '}
                <button
                  type="button"
                  onClick={onRegisterClick}
                  className="text-blue-600 hover:underline"
                  disabled={loading}
                >
                  Sign up
                </button>
              </div>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}