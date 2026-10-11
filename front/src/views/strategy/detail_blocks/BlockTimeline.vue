<template>
  <div class="block-timeline">
    <!-- 时间线（design D5）：信号日期序列 + 状态演进 -->
    <div class="timeline">
      <div v-for="(ev, i) in events" :key="i" class="timeline-item">
        <div class="timeline-dot" :class="dotClass(ev.state)"></div>
        <div class="timeline-body">
          <div class="timeline-head">
            <span class="num timeline-date">{{ ev.date }}</span>
            <span class="timeline-event">{{ ev.event }}</span>
          </div>
        </div>
      </div>
      <div v-if="events.length === 0" class="timeline-empty">暂无时间线事件</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/** timeline 块：时间线（信号日期序列 + 状态演进，detail API timeline 字段） */
defineProps<{
  events: { date: string; event: string; state: string }[]
}>()

/** 状态点配色：done/success → 绿（--fall，A 股完成语义），其余按 states 色系近似 */
function dotClass(state: string): string {
  if (state === 'done') return 'dot--done'
  if (state === 'running' || state === 'triggered') return 'dot--rise'
  if (state === 'expired' || state === 'broken') return 'dot--warning'
  return 'dot--info'
}
</script>

<style scoped>
.timeline {
  display: flex;
  flex-direction: column;
}
.timeline-item {
  display: flex;
  gap: var(--sp-md);
  padding: 6px 0;
  position: relative;
}
.timeline-item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 20px;
  bottom: -6px;
  width: 1px;
  background: var(--border-base);
}
.timeline-dot {
  width: 11px;
  height: 11px;
  border-radius: var(--r-full);
  flex-shrink: 0;
  margin-top: 3px;
}
.dot--info { background: var(--accent-base); }
.dot--rise { background: var(--rise); }
.dot--done { background: var(--fall); }
.dot--warning { background: var(--warning); }
.timeline-body {
  min-width: 0;
}
.timeline-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-sm);
  flex-wrap: wrap;
}
.timeline-date {
  font-size: 11px;
  color: var(--text-disabled);
  flex-shrink: 0;
}
.timeline-event {
  font-size: 12px;
  color: var(--text-primary);
}
.timeline-empty {
  padding: var(--sp-sm) 0;
  font-size: 12px;
  color: var(--text-disabled);
}
</style>
