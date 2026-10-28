import { spawn } from 'node:child_process';

const procs = [
  spawn('node', ['server/index.mjs'], { stdio: 'inherit', env: process.env }),
  spawn('npx', ['vite'], { stdio: 'inherit', env: process.env }),
];

const stop = () => {
  for (const p of procs) p.kill('SIGINT');
  process.exit(0);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
for (const p of procs) p.on('exit', (code) => { if (code) stop(); });
