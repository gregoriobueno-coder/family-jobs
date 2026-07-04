const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const babel = require('@babel/core');
const script = html.split('<script type="text/babel" data-presets="react,env">')[1].split('</script>')[0];
try {
  babel.transformSync(script, { presets: ['@babel/preset-react'] });
  console.log("REACT SYNTAX OKAY!");
} catch (e) {
  console.error("REACT SYNTAX ERROR:", e);
  process.exit(1);
}
