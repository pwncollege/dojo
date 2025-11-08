// User and Authentication Types
export interface User {
  id: number
  email: string
  username: string
  name?: string
  website?: string
  affiliation?: string
  country?: string
  hidden: boolean
  banned: boolean
  verified: boolean
  created: string
  type: 'admin' | 'user'
}

export interface AuthResponse {
  success: boolean
  user?: User
  token?: string
  message?: string
}

// Resource Types
export interface Resource {
  id: string
  name: string
  type: 'markdown' | 'lecture' | 'header'
  content?: string
  video?: string
  playlist?: string
  slides?: string
  expandable?: boolean
}

// Dojo Types
export interface DojoModule {
  id: string
  name: string
  description?: string
  unified_items: Array<{
    item_type: 'resource' | 'challenge'
    id: string
    name?: string
    type?: 'markdown' | 'lecture' | 'header'
    content?: string
    video?: string
    playlist?: string
    slides?: string
    expandable?: boolean
    description?: string
    required?: boolean
  }>
  challenges: Challenge[]
  resources?: Resource[]
  type?: string
}

export interface Dojo {
  id: string
  name: string
  description?: string
  password?: boolean
  award?: string
  type?: string
  reference_id?: string
  modules: DojoModule[]
  official: boolean
  data?: {
    [key: string]: any
  }
}

export interface DojoListResponse {
  dojos: Dojo[]
  success: boolean
}

export interface DojoResponse {
  dojo: Dojo
  success: boolean
}

// Challenge Types
export interface ChallengeFile {
  location: string
  sha1sum: string
}

export interface Challenge {
  id: string
  name: string
  description?: string
  category?: string
  value: number
  type: string
  state: 'visible' | 'hidden'
  max_attempts?: number
  files?: ChallengeFile[]
  tags?: string[]
  hints?: Hint[]
  requirements?: number[]
  next_id?: number
  solves?: number
  solved?: boolean
  attempts?: number
}

export interface ChallengeResponse {
  challenge: Challenge
  success: boolean
}

export interface ChallengeListResponse {
  challenges: Challenge[]
  success: boolean
}

// Submission Types
export interface Submission {
  id: number
  challenge_id: number
  user_id: number
  team_id?: number
  ip: string
  provided: string
  type: 'correct' | 'incorrect'
  date: string
}

export interface SubmissionResponse {
  success: boolean
  data?: {
    status: 'correct' | 'incorrect' | 'already_solved' | 'paused'
    message?: string
  }
}

// Hint Types
export interface Hint {
  id: number
  challenge_id: number
  content: string
  cost: number
  requirements?: number[]
}

export interface HintResponse {
  hint: Hint
  success: boolean
}

// Scoreboard Types
export interface ScoreboardEntry {
  account_id: number
  name: string
  score: number
  pos: number
}

export interface ScoreboardResponse {
  data: ScoreboardEntry[]
  success: boolean
}

// Statistics Types
export interface UserStats {
  id: number
  name: string
  score: number
  place: number
  solves: Challenge[]
  awards: any[]
}

export interface StatsResponse {
  data: UserStats
  success: boolean
}

// Team Types (if teams are enabled)
export interface Team {
  id: number
  name: string
  email?: string
  website?: string
  affiliation?: string
  country?: string
  bracket?: string
  hidden: boolean
  banned: boolean
  created: string
  captain_id: number
  members: User[]
}

export interface TeamResponse {
  team: Team
  success: boolean
}

// Awards/Badges Types
export interface Award {
  id: number
  name: string
  description?: string
  date: string
  value?: number
  category?: string
  icon?: string
}

export interface AwardResponse {
  awards: Award[]
  success: boolean
}

// Error Response
export interface ErrorResponse {
  success: false
  message: string
  errors?: {
    [key: string]: string[]
  }
}
