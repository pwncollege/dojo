import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useSubmitChallengeSolution } from '@/hooks/useDojo'
import { Flag, Loader2, CheckCircle, AlertCircle } from 'lucide-react'

interface FlagSubmissionProps {
  dojoId: string
  moduleId: string
  challengeId: string
  challengeName: string
}

export function FlagSubmission({ dojoId, moduleId, challengeId, challengeName }: FlagSubmissionProps) {
  const [flag, setFlag] = useState('')
  const [lastSubmission, setLastSubmission] = useState<{
    flag: string
    result: { success: boolean; status?: string; error?: string }
  } | null>(null)

  const submitSolution = useSubmitChallengeSolution()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!flag.trim()) return

    const submissionData = {
      dojoId,
      moduleId,
      challengeId,
      submission: { submission: flag.trim() }
    }


    try {
      const result = await submitSolution.mutateAsync(submissionData)

      setLastSubmission({
        flag: flag.trim(),
        result
      })

      // Clear flag input only if successful
      if (result.success && result.status !== 'authentication_required') {
        setFlag('')
      }
    } catch (error: any) {

      let errorMessage = 'Submission failed'

      // Check for specific error types
      if (error?.status === 401 || error?.status === 403) {
        errorMessage = 'Authentication required. Please log in to submit flags.'
      } else if (error?.status === 404) {
        errorMessage = 'Challenge endpoint not found. This may be due to incorrect challenge mapping or the challenge not being properly configured in CTFd.'
      } else if (error?.status === 500) {
        errorMessage = 'Server error. This might be due to authentication issues or the backend being unavailable.'
      } else if (error?.response) {
        errorMessage = error.response.message || error.response.error || `HTTP ${error.status}`
      } else if (error?.message) {
        errorMessage = error.message
      }

      setLastSubmission({
        flag: flag.trim(),
        result: {
          success: false,
          error: errorMessage
        }
      })
    }
  }

  const getSubmissionStatus = () => {
    if (!lastSubmission) return null

    if (lastSubmission.result.success) {
      // Check for authentication required status
      if (lastSubmission.result.status === 'authentication_required') {
        return (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <strong>Authentication Required</strong> Please log in to the dojo platform to submit flags.
            </AlertDescription>
          </Alert>
        )
      }

      return (
        <Alert className="border-green-200 bg-green-50">
          <CheckCircle className="h-4 w-4 text-green-600" />
          <AlertDescription className="text-green-700">
            <strong>Correct!</strong> Flag "{lastSubmission.flag}" was accepted.
            {lastSubmission.result.status && (
              <div className="mt-1 text-sm">{lastSubmission.result.status}</div>
            )}
          </AlertDescription>
        </Alert>
      )
    } else {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            <strong>Incorrect!</strong> Flag "{lastSubmission.flag}" was rejected.
            {lastSubmission.result.error && (
              <div className="mt-1 text-sm">{lastSubmission.result.error}</div>
            )}
          </AlertDescription>
        </Alert>
      )
    }
  }

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Flag className="h-5 w-5" />
          Submit Flag for {challengeName}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {getSubmissionStatus()}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex gap-2">
            <Input
              type="text"
              value={flag}
              onChange={(e) => setFlag(e.target.value)}
              placeholder="Enter your flag here..."
              disabled={submitSolution.isPending}
              className="flex-1"
              autoComplete="off"
            />
            <Button
              type="submit"
              disabled={submitSolution.isPending || !flag.trim()}
              className="min-w-[100px]"
            >
              {submitSolution.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Submitting
                </>
              ) : (
                <>
                  <Flag className="h-4 w-4 mr-2" />
                  Submit
                </>
              )}
            </Button>
          </div>

          <div className="text-sm text-muted-foreground">
            Enter the flag you found for this challenge. Flags are typically in the format: pwn.college{"{...}"}
            <br />
            <strong>Note:</strong> You must be logged in to the dojo platform to submit flags.
          </div>
        </form>
      </CardContent>
    </Card>
  )
}