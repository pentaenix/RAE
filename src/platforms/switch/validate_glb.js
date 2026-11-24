// Independent Khronos validation; the validator is installed in the local cache.
const fs = require('fs');
const [packagePath, source, output] = process.argv.slice(2);
const validator = require(packagePath);
validator.validateBytes(new Uint8Array(fs.readFileSync(source)), { uri: source }).then(report => {
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  if (report.issues.numErrors) {
    console.error(JSON.stringify(report.issues));
    process.exitCode = 1;
  }
}).catch(error => { console.error(error); process.exitCode = 1; });
