import { get, post, put } from './index'
import type { User, UserSettings, AuthSession } from '../types'

export interface MeResponse {
  user: User
  settings: UserSettings
  oauth_accounts: Array<{
    provider: string
    provider_name: string
    provider_avatar: string
  }>
}

export async function fetchMe(): Promise<MeResponse> {
  return get<MeResponse>('/api/auth/me')
}

export async function updateMe(data: Partial<User>): Promise<User> {
  return put<User>('/api/auth/me', data)
}

export async function fetchSettings(): Promise<UserSettings> {
  return get<UserSettings>('/api/auth/me/settings')
}

export async function updateSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
  return put<UserSettings>('/api/auth/me/settings', settings)
}

export async function fetchSessions(): Promise<AuthSession[]> {
  const res = await get<{ sessions: AuthSession[] }>('/api/auth/me/sessions')
  return res.sessions
}

export async function logout(): Promise<void> {
  await post('/api/auth/logout', {})
}

export async function logoutAll(): Promise<void> {
  await post('/api/auth/logout/all', {})
}
