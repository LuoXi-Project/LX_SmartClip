const fs = require('fs')

const pkgPath = process.argv[2]
const version = process.argv[3]

if (!pkgPath || !version) {
  console.error('Usage: node sync_package_version.js <package.json> <version>')
  process.exit(1)
}

const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
pkg.version = version
fs.writeFileSync(pkgPath, `${JSON.stringify(pkg, null, 2)}\n`, 'utf8')
