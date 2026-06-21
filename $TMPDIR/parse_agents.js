const fs = require('fs');
const PATH = '/Users/kalence/.claude/projects/-Users-kalence-Desktop-01-A-------/90448dbd-6558-4cde-a468-f7641a6943ee/subagents/workflows/wf_07c14191-01b/';
const files = fs.readdirSync(PATH).filter(f => f.endsWith('.jsonl') && f !== 'journal.jsonl').sort();
files.forEach(f => {
  const content = fs.readFileSync(PATH + f, 'utf8');
  const lines = content.split('\n').filter(Boolean);
  const lastLine = JSON.parse(lines[lines.length - 1]);
  console.log('=== ' + f + ' ===');
  console.log('role:', lastLine.message?.role || '?');
  if (lastLine.message?.content) {
    const contentParts = lastLine.message.content;
    const toolUse = contentParts.find(c => c.type === 'tool_use');
    if (toolUse && toolUse.input) {
      const input = toolUse.input;
      const techs = input.techniques || [];
      const filesRead = input.filesRead || [];
      const keyFindings = input.keyFindings || [];
      console.log('techniques:', techs.length);
      console.log('filesRead:', filesRead.length);
      console.log('keyFindings:', keyFindings.length);
      techs.forEach((t, i) => console.log('  tech[' + i + ']:', t.name, '|', (t.method || '').slice(0, 40), '|', t.currentStatus));
    } else {
      console.log('text:', JSON.stringify(contentParts[0]?.text || '').slice(0, 200));
      for (let li = lines.length - 2; li >= 0; li--) {
        try {
          const msg = JSON.parse(lines[li]);
          if (msg.message?.content) {
            const tu = msg.message.content.find(c => c.type === 'tool_use' && c.input?.techniques);
            if (tu) {
              console.log('FOUND in earlier message #' + li + ': techniques=' + tu.input.techniques.length);
              console.log('  keys:', Object.keys(tu.input));
              // Print first 3 techniques
              tu.input.techniques.slice(0, 3).forEach((t, i) => console.log('  ' + i + ':', t.name, '|', (t.method || '').slice(0, 50), '|', t.currentStatus));
              break;
            }
          }
        } catch (e) { }
      }
    }
  }
  console.log('');
});
