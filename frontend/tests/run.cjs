const {execFileSync}=require('node:child_process');
const fs=require('node:fs');
execFileSync(process.execPath,['node_modules/typescript/bin/tsc','--target','ES2022','--module','commonjs','--moduleResolution','node','--jsx','react-jsx','--strict','--skipLibCheck','--outDir','.test-dist','src/engineering/diff.ts','src/engineering/navigation.ts','src/engineering/state.ts','src/engineering/EngineeringChrome.tsx'],{stdio:'inherit'});
fs.writeFileSync('.test-dist/package.json',JSON.stringify({type:'commonjs'}));
execFileSync(process.execPath,['--test','tests/workspace.test.cjs'],{stdio:'inherit'});
