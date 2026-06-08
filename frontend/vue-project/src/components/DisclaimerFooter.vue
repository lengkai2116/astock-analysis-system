<template>
  <div class="disclaimer-footer">
    <div class="disclaimer-content">
      <span class="disclaimer-icon">⚠️</span>
      <span class="disclaimer-text">
        本系统输出为策略研究与决策支持信息，不连接券商交易接口，不自动下单，不执行真实资金调仓。所有结论仅供研究参考。
      </span>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DisclaimerFooter',
}
</script>

<style scoped>
.disclaimer-footer {
  margin-top: 32px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-default, rgba(255,255,255,0.08));
  background: var(--bg-subtle, rgba(255,255,255,0.04));
  border-radius: var(--radius-sm, 6px);
}

.disclaimer-content {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.disclaimer-icon {
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1.6;
}

.disclaimer-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted, #64748b);
}
</style>
