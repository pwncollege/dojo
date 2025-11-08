'use client'

import { Button } from '@/components/ui/button'
import { Share2 } from 'lucide-react'

interface SocialShareButtonsProps {
  username: string
}

export function SocialShareButtons({ username }: SocialShareButtonsProps) {
  const shareUrl = typeof window !== 'undefined' ? window.location.href : ''
  const shareText = `Check out ${username}'s pwn.college profile!`

  const handleShare = () => {
    if (navigator.share) {
      navigator.share({
        title: `${username} | pwn.college`,
        text: shareText,
        url: shareUrl,
      }).catch(() => {
        // User cancelled or error, do nothing
      })
    } else {
      // Fallback: copy to clipboard
      navigator.clipboard.writeText(shareUrl)
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleShare}
      className="gap-2"
    >
      <Share2 className="h-4 w-4" />
      Share Profile
    </Button>
  )
}
