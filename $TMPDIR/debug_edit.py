#!/usr/bin/env python3
with open('/Users/kalence/Desktop/01-A股股票分析系统/backend/app/routes/realtime.py', 'r') as f:
    content = f.read()

old_start = "    def _get_stock_realtime_data"
old_end = "            return None"

# Find the method
idx = content.index(old_start)
end_idx = content.index(old_end, idx) + len(old_end)

old = content[idx:end_idx]
print(f"Old method text ({len(old)} bytes):")
for line in old.split('\n'):
    print(repr(line))
