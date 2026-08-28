const fs = require('fs');
const { execSync } = require('child_process');

const PATCH = 'patches/premium-unlock.patch';
const MARKER_FILE = 'src/utils/request/user.ts';
const MARKERS = ['Pro unlock:', 'premium unlock fallback'];

try {
  if (!fs.existsSync(PATCH)) {
    console.log('Patch file not found. Skipping premium patch.');
    process.exit(0);
  }
  if (!fs.existsSync(MARKER_FILE)) {
    console.log('Target file not found. Skipping premium patch.');
    process.exit(0);
  }
  const content = fs.readFileSync(MARKER_FILE, 'utf8');
  const alreadyApplied = MARKERS.some((m) => content.includes(m));
  if (alreadyApplied) {
    console.log('Premium patch already applied.');
    process.exit(0);
  }
  console.log('Applying premium patch...');
  execSync(`git apply ${PATCH}`, { stdio: 'inherit' });
  console.log('Premium patch applied.');
} catch (err) {
  console.error('Error applying premium patch:', err.message);
  process.exit(1);
}
