// Parse browser sources explicitly as ES modules. Automatic .js mode detection
// can suppress a module parse error in some Node versions.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.join(__dirname, '..', 'openreporting', 'static', 'app');
function check(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) check(file);
    else if (entry.name.endsWith('.js')) {
      const result = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: fs.readFileSync(file), encoding: 'utf8' });
      if (result.status !== 0) {
        console.error(`${file}\n${result.stderr || result.error || 'Module parse failed'}`);
        process.exit(1);
      }
    }
  }
}
check(root);
console.log('All browser ES modules passed syntax checks');
