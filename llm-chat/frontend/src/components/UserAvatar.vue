<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  src?: string
  name?: string
  size?: number | string
}>()

const avatarSize = computed(() => {
  if (typeof props.size === 'number') return `${props.size}px`
  return props.size || '32px'
})

const initials = computed(() => {
  if (!props.name) return '?'
  return props.name.charAt(0).toUpperCase()
})

const bgColor = computed(() => {
  if (!props.name) return '#94a3b8'
  const colors = [
    '#3b82f6', '#10b981', '#f59e0b', '#ef4444', 
    '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'
  ]
  let hash = 0
  for (let i = 0; i < props.name.length; i++) {
    hash = props.name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
})
</script>

<template>
  <div 
    class="user-avatar" 
    :style="{ width: avatarSize, height: avatarSize, backgroundColor: src ? 'transparent' : bgColor }"
  >
    <img v-if="src" :src="src" :alt="name" class="avatar-img" referrerpolicy="no-referrer" @error="$el.style.display='none'" />
    <span v-else class="avatar-initials">{{ initials }}</span>
  </div>
</template>

<style scoped>
.user-avatar {
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
  user-select: none;
  border: none;
  background-color: #f3f4f6;
  transition: transform 0.2s ease;
}

.avatar-img {
  display: block;
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
  object-fit: cover;
  border-radius: 50%;
}

.avatar-initials {
  color: white;
  font-weight: 600;
  font-size: 0.8em;
}

.user-avatar:hover {
  transform: scale(1.05);
}
</style>
