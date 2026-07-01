const fs = require('fs');
const { execSync } = require('child_process');

try {
  const filePath = 'src/utils/request/user.ts';
  if (!fs.existsSync(filePath)) {
    console.log('Target file not found. Skipping patch.');
    process.exit(0);
  }
  const content = fs.readFileSync(filePath, 'utf8');
  if (content.includes('Pro unlock: always return a valid pro user')) {
    console.log('Premium patch is already applied.');
  } else {
    console.log('Applying premium patch...');
    execSync('git apply patches/premium-unlock.patch', { stdio: 'inherit' });
  }
} catch (err) {
  console.error('Error applying premium patch:', err.message);
  process.exit(1);
}
