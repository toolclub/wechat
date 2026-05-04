<script setup lang="ts">
import { useAuth } from '../composables/useAuth'

defineEmits(['skip'])
const auth = useAuth()
</script>

<template>
  <div class="login-overlay" @click.self="$emit('skip')">
    <div class="login-card">
      <div class="login-header">
        <div class="logo-wrapper">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
            <path d="M16 4C16 4 17.5 11 23 14C17.5 17 16 24 16 24C16 24 14.5 17 9 14C14.5 11 16 4 16 4Z" fill="#00AEEC"/>
            <path d="M25 7C25 7 25.6 9.8 27.5 10.7C25.6 11.6 25 14.4 25 14.4C25 14.4 24.4 11.6 22.5 10.7C24.4 9.8 25 7 25 7Z" fill="#FB7299" opacity="0.7"/>
          </svg>
        </div>
        <h2>登录 ChatFlow</h2>
        <p>同步对话历史，跨设备访问</p>
      </div>

      <div class="login-body">
        <button class="oauth-btn google" @click="auth.loginWithOAuth('google')">
          <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
          <span>使用 Google 账号登录</span>
        </button>

        <button class="oauth-btn github" @click="auth.loginWithOAuth('github')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
          <span>使用 GitHub 账号登录</span>
        </button>
      </div>

      <div class="login-footer">
        <button class="skip-btn" @click="$emit('skip')">暂时跳过，匿名使用</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: white;
  border-radius: 20px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  padding: 40px 36px 32px;
  text-align: center;
  animation: slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from { transform: translateY(24px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

body.dark .login-card {
  background: #1e293b;
  color: #f1f5f9;
}

.login-header {
  margin-bottom: 32px;
}

.logo-wrapper {
  display: inline-flex;
  padding: 10px;
  background: linear-gradient(135deg, #E3F6FD 0%, #FDE8EF 100%);
  border-radius: 14px;
  margin-bottom: 16px;
}

.login-header h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 4px;
  color: #1e293b;
}

body.dark .login-header h2 {
  color: #f1f5f9;
}

.login-header p {
  font-size: 13px;
  color: #64748b;
  margin: 0;
}

.login-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.oauth-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  border: 1.5px solid #e2e8f0;
  background: white;
  color: #334155;
}

body.dark .oauth-btn {
  background: #334155;
  border-color: #475569;
  color: #f1f5f9;
}

.oauth-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  border-color: #cbd5e1;
}

.oauth-btn:active {
  transform: translateY(0);
}

.oauth-btn.google:hover {
  border-color: #4285F4;
  box-shadow: 0 4px 12px rgba(66, 133, 244, 0.15);
}

.oauth-btn.github {
  color: #24292e;
}

body.dark .oauth-btn.github {
  color: #f1f5f9;
}

.oauth-btn.github:hover {
  border-color: #24292e;
  box-shadow: 0 4px 12px rgba(36, 41, 46, 0.15);
}

.login-footer {
  margin-top: 28px;
}

.skip-btn {
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 13px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  transition: all 0.15s;
}

.skip-btn:hover {
  color: #64748b;
  background: #f1f5f9;
}

body.dark .skip-btn:hover {
  background: #334155;
}
</style>
