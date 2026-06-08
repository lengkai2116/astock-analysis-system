<template>
  <div
    class="code-editor"
    :class="{ 'theme-dark': dark }"
  >
    <!-- 工具栏 -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <a-select
          v-model="currentTemplate"
          size="small"
          style="width: 180px"
          placeholder="选择模板"
          @change="loadTemplate"
        >
          <a-select-option value="">
            — 自定义 —
          </a-select-option>
          <a-select-option-group label="均线策略">
            <a-select-option value="ma_cross">
              均线交叉
            </a-select-option>
            <a-select-option value="ma_trend">
              均线趋势
            </a-select-option>
          </a-select-option-group>
          <a-select-option-group label="震荡指标">
            <a-select-option value="rsi_divergence">
              RSI 背离
            </a-select-option>
            <a-select-option value="macd_cross">
              MACD 金叉死叉
            </a-select-option>
            <a-select-option value="kdj_overbought">
              KDJ 超买超卖
            </a-select-option>
          </a-select-option-group>
          <a-select-option-group label="组合策略">
            <a-select-option value="ma_macd_combined">
              MA+MACD 组合
            </a-select-option>
            <a-select-option value="boll_rsi_combined">
              BOLL+RSI 组合
            </a-select-option>
          </a-select-option-group>
          <a-select-option-group label="选股">
            <a-select-option value="volume_breakout">
              放量突破
            </a-select-option>
            <a-select-option value="golden_valley">
              黄金谷
            </a-select-option>
          </a-select-option-group>
        </a-select>
      </div>
      <div class="toolbar-right">
        <a-tooltip title="格式化代码">
          <a-button
            size="small"
            :disabled="!editor"
            @click="formatCode"
          >
            美化
          </a-button>
        </a-tooltip>
        <a-tooltip title="运行策略">
          <a-button
            type="primary"
            size="small"
            :loading="running"
            icon="caret-right"
            @click="runStrategy"
          >
            运行
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- 编辑器主体 -->
    <div
      ref="editorRef"
      class="editor-body"
    />

    <!-- 执行结果 -->
    <div
      v-if="runResult"
      class="editor-result"
      :class="runResultClass"
    >
      <div class="result-header">
        <span>执行结果</span>
        <a-button
          type="link"
          size="small"
          @click="runResult = null"
        >
          x
        </a-button>
      </div>
      <div class="result-body">
        <pre><code>{{ runResult }}</code></pre>
      </div>
    </div>
  </div>
</template>

<script>
import CodeMirror from 'codemirror'
import 'codemirror/lib/codemirror.css'
import 'codemirror/mode/python/python'
import 'codemirror/addon/comment/comment'
import 'codemirror/addon/edit/closebrackets'
import 'codemirror/addon/edit/matchbrackets'
import 'codemirror/addon/fold/foldcode'
import 'codemirror/addon/fold/foldgutter'
import 'codemirror/addon/fold/brace-fold'
import 'codemirror/addon/fold/indent-fold'
import axios from '@/utils/request'

const TEMPLATES = {
  ma_cross: {
    name: '均线交叉', description: '短期均线上穿/下穿长期均线生成买卖信号',
    code: [
      '## 均线交叉策略',
      '##',
      '## @strategy(name="MA_Cross", desc="均线交叉")',
      '## @param(name="fast", type="int", default=5, min=3, max=60, desc="快线周期")',
      '## @param(name="slow", type="int", default=20, min=10, max=120, desc="慢线周期")',
      '',
      'def calculate(data, params=None):',
      '    """计算均线交叉信号"""',
      '    if params is None:',
      "        params = {'fast': 5, 'slow': 20}",
      '    fast = params["fast"]',
      '    slow = params["slow"]',
      "    close = data['close']",
      '    ma_fast = close.rolling(window=fast).mean()',
      '    ma_slow = close.rolling(window=slow).mean()',
      '    golden_cross = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))',
      '    dead_cross = (ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))',
      '    plots = [',
      "        {'name': 'MA'+str(fast), 'data': ma_fast.tolist()},",
      "        {'name': 'MA'+str(slow), 'data': ma_slow.tolist()}",
      '    ]',
      '    signals = []',
      '    for i in range(len(data)):',
      '        if golden_cross.iloc[i]:',
      "            signals.append({'time': i, 'type': 'buy', 'price': float(close.iloc[i]), 'text': '金叉'})",
      '        elif dead_cross.iloc[i]:',
      "            signals.append({'time': i, 'type': 'sell', 'price': float(close.iloc[i]), 'text': '死叉'})",
      "    return {'plots': plots, 'signals': signals}"
    ].join('\n')
  },
  macd_cross: {
    name: 'MACD 金叉死叉', description: 'MACD DIF与DEA交叉信号',
    code: [
      '## MACD 金叉死叉策略',
      '## @strategy(name="MACD_Cross", desc="MACD交叉")',
      '## @param(name="fast", type="int", default=12, desc="快线周期")',
      '## @param(name="slow", type="int", default=26, desc="慢线周期")',
      '## @param(name="signal", type="int", default=9, desc="信号线周期")',
      '',
      'def calculate(data, params=None):',
      '    if params is None:',
      "        params = {'fast': 12, 'slow': 26, 'signal': 9}",
      "    close = data['close']",
      '    fast, slow, sig = params["fast"], params["slow"], params["signal"]',
      '    ema_fast = close.ewm(span=fast, adjust=False).mean()',
      '    ema_slow = close.ewm(span=slow, adjust=False).mean()',
      '    dif = ema_fast - ema_slow',
      '    dea = dif.ewm(span=sig, adjust=False).mean()',
      '    macd_hist = 2 * (dif - dea)',
      '    golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))',
      '    dead = (dif < dea) & (dif.shift(1) >= dea.shift(1))',
      '    plots = [',
      "        {'name': 'DIF', 'data': dif.tolist()},",
      "        {'name': 'DEA', 'data': dea.tolist()},",
      "        {'name': 'MACD', 'data': macd_hist.tolist(), 'type': 'bar'}",
      '    ]',
      '    signals = []',
      '    for i in range(len(data)):',
      '        if golden.iloc[i]:',
      "            signals.append({'time': i, 'type': 'buy', 'price': float(close.iloc[i]), 'text': 'MACD金叉'})",
      '        elif dead.iloc[i]:',
      "            signals.append({'time': i, 'type': 'sell', 'price': float(close.iloc[i]), 'text': 'MACD死叉'})",
      "    return {'plots': plots, 'signals': signals}"
    ].join('\n')
  },
  rsi_divergence: {
    name: 'RSI 背离', description: 'RSI 超买超卖检测',
    code: [
      '## RSI 超买超卖策略',
      '## @strategy(name="RSI_OBOS", desc="RSI超买超卖")',
      '## @param(name="period", type="int", default=14, desc="RSI周期")',
      '## @param(name="oversold", type="int", default=30, desc="超卖阈值")',
      '## @param(name="overbought", type="int", default=70, desc="超买阈值")',
      '',
      'def calculate(data, params=None):',
      '    if params is None:',
      "        params = {'period': 14, 'oversold': 30, 'overbought': 70}",
      "    close = data['close']",
      '    period = params["period"]',
      '    delta = close.diff()',
      '    gain = delta.where(delta > 0, 0).rolling(window=period).mean()',
      '    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()',
      '    rs = gain / loss',
      '    rsi = 100 - (100 / (1 + rs))',
      '    plots = [{"name": "RSI", "data": rsi.tolist()}]',
      '    signals = []',
      '    for i in range(len(data)):',
      '        if rsi.iloc[i] < params["oversold"]:',
      "            signals.append({'time': i, 'type': 'buy', 'price': float(close.iloc[i]), 'text': 'RSI超卖'})",
      '        elif rsi.iloc[i] > params["overbought"]:',
      "            signals.append({'time': i, 'type': 'sell', 'price': float(close.iloc[i]), 'text': 'RSI超买'})",
      "    return {'plots': plots, 'signals': signals}"
    ].join('\n')
  },
  boll_rsi_combined: {
    name: 'BOLL+RSI 组合', description: '布林带+RSI组合信号',
    code: [
      '## BOLL+RSI 组合策略',
      '## @strategy(name="BOLL_RSI", desc="布林带+RSI组合")',
      '## @param(name="boll_period", type="int", default=20, desc="布林带周期")',
      '## @param(name="rsi_period", type="int", default=14, desc="RSI周期")',
      '',
      'def calculate(data, params=None):',
      '    if params is None:',
      "        params = {'boll_period': 20, 'rsi_period': 14, 'boll_std': 2}",
      "    close = data['close']",
      '    bp = params["boll_period"]',
      '    ma = close.rolling(window=bp).mean()',
      '    std = close.rolling(window=bp).std()',
      '    upper = ma + params["boll_std"] * std',
      '    lower = ma - params["boll_std"] * std',
      '    delta = close.diff()',
      '    gain = delta.where(delta > 0, 0).rolling(window=params["rsi_period"]).mean()',
      '    loss = (-delta.where(delta < 0, 0)).rolling(window=params["rsi_period"]).mean()',
      '    rsi = 100 - (100 / (1 + gain / loss))',
      '    signals = []',
      '    for i in range(len(data)):',
      '        if close.iloc[i] <= lower.iloc[i] and rsi.iloc[i] < 30:',
      "            signals.append({'time': i, 'type': 'buy', 'price': float(close.iloc[i]), 'text': 'BOLL下轨+RSI超卖'})",
      '        elif close.iloc[i] >= upper.iloc[i] and rsi.iloc[i] > 70:',
      "            signals.append({'time': i, 'type': 'sell', 'price': float(close.iloc[i]), 'text': 'BOLL上轨+RSI超买'})",
      "    return {'signals': signals}"
    ].join('\n')
  },
  volume_breakout: {
    name: '放量突破', description: '成交量放量突破策略',
    code: [
      '## 放量突破策略',
      '## @strategy(name="Vol_Breakout", desc="放量突破")',
      '## @param(name="vol_factor", type="float", default=1.5, desc="放量倍数")',
      '## @param(name="ma_period", type="int", default=20, desc="均量线周期")',
      '',
      'def calculate(data, params=None):',
      '    if params is None:',
      "        params = {'vol_factor': 1.5, 'ma_period': 20}",
      "    close = data['close']",
      "    volume = data['volume']",
      '    vf = params["vol_factor"]',
      '    vol_ma = volume.rolling(window=params["ma_period"]).mean()',
      '    price_ma = close.rolling(window=params["ma_period"]).mean()',
      '    vol_surge = volume > vol_ma * vf',
      '    breakout = vol_surge & (close > price_ma) & (close.shift(1) <= price_ma.shift(1))',
      '    signals = []',
      '    for i in range(len(data)):',
      '        if breakout.iloc[i]:',
      "            signals.append({'time': i, 'type': 'buy', 'price': float(close.iloc[i]), 'text': '放量突破'})",
      "    return {'signals': signals}"
    ].join('\n')
  }
}

export default {
  name: 'CodeEditor',
  props: {
    value: { type: String, default: '' },
    dark: { type: Boolean, default: true },
    stockCode: { type: String, default: '' }
  },
  data() {
    return {
      editor: null,
      currentTemplate: '',
      running: false,
      runResult: null,
      runResultClass: ''
    }
  },
  watch: {
    dark() { this.updateTheme() }
  },
  mounted() {
    this.initEditor()
  },
  beforeUnmount() {
    if (this.editor) {
      this.editor.toTextArea()
      this.editor = null
    }
  },
  methods: {
    initEditor() {
      this.$nextTick(() => {
        if (!this.$refs.editorRef) return
        this.editor = CodeMirror(this.$refs.editorRef, {
          value: this.value || '## 在此输入 Python 策略代码\n## 使用 @strategy / @param 注解定义策略\n\ndef calculate(data, params=None):\n    close = data[\'close\']\n    signals = []\n    return {\'signals\': signals}\n',
          mode: 'text/x-python',
          theme: this.dark ? 'monokai' : 'default',
          lineNumbers: true,
          indentUnit: 4,
          tabSize: 4,
          matchBrackets: true,
          autoCloseBrackets: true,
          foldGutter: true,
          gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
          extraKeys: {
            'Cmd-/': 'toggleComment',
            'Ctrl-/': 'toggleComment'
          }
        })
        this.editor.on('change', () => {
          this.$emit('input', this.editor.getValue())
        })
      })
    },

    loadTemplate(templateId) {
      if (!templateId) return
      const tmpl = TEMPLATES[templateId]
      if (tmpl && this.editor) {
        this.editor.setValue(tmpl.code)
        this.editor.execCommand('selectAll')
        this.editor.execCommand('indentAuto')
        this.editor.setCursor(0, 0)
        this.$emit('template-loaded', tmpl)
      }
    },

    formatCode() {
      if (!this.editor) return
      this.editor.execCommand('selectAll')
      this.editor.execCommand('indentAuto')
      this.editor.setCursor(0, 0)
    },

    updateTheme() {
      if (this.editor) {
        this.editor.setOption('theme', this.dark ? 'monokai' : 'default')
      }
    },

    async runStrategy() {
      if (!this.editor || !this.stockCode) {
        this.runResult = '请先选择股票\n'
        this.runResultClass = 'result-error'
        return
      }
      const code = this.editor.getValue()
      if (!code.trim()) {
        this.runResult = '策略代码为空\n'
        this.runResultClass = 'result-error'
        return
      }
      this.running = true
      this.runResult = '执行中...\n'
      this.runResultClass = 'result-info'
      try {
        const res = await axios.post('/api/v3/strategy/run', {
          code: code,
          ts_code: this.stockCode
        }, { timeout: 30000 })
        if (res.success && res.data) {
          const signals = res.data.signals || []
          const plots = res.data.plots || []
          this.runResult = '执行成功\n'
          this.runResult += '输出指标: ' + plots.length + ' 个\n'
          this.runResult += '生成信号: ' + signals.length + ' 个\n'
          signals.forEach(s => {
            this.runResult += '[' + s.type.toUpperCase() + '] ' + (s.text || '') + '\n'
          })
          this.runResultClass = 'result-success'
          this.$emit('strategy-result', res.data)
        } else {
          this.runResult = '执行失败: ' + (res.message || '未知错误') + '\n'
          this.runResultClass = 'result-error'
        }
      } catch (err) {
        this.runResult = '执行出错: ' + (err.message || '网络错误') + '\n'
        this.runResultClass = 'result-error'
      } finally {
        this.running = false
      }
    }
  }
}
</script>

<style scoped>
.code-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: #1e293b;
}
.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: #0f172a;
  border-bottom: 1px solid #2a2a2a;
  flex-shrink: 0;
}
.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.editor-body {
  flex: 1;
  overflow: hidden;
}
.editor-body :deep(.CodeMirror) {
  height: 100% !important;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}
.editor-body :deep(.CodeMirror-gutters) {
  background: #0f172a;
  border-right: 1px solid #2a2a2a;
}
.editor-body :deep(.CodeMirror-linenumber) {
  color: #475569;
  padding: 0 8px;
}
.editor-body :deep(.cm-s-monokai) {
  background: #1e293b;
}
.editor-body :deep(.cm-comment) {
  color: #64748b;
  font-style: italic;
}
.editor-result {
  flex-shrink: 0;
  max-height: 200px;
  border-top: 1px solid #2a2a2a;
  overflow-y: auto;
}
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  background: #0f172a;
  color: #94a3b8;
  font-size: 12px;
}
.result-body {
  padding: 8px 12px;
}
.result-body pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}
.result-body code {
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.result-success .result-body code { color: #4ade80; }
.result-error .result-body code { color: #ef4444; }
.result-info .result-body code { color: #60a5fa; }
</style>
