const pdf2html = require('pdf2html');
const fs = require('fs');

const html = await pdf2html.html('NewCookbook.pdf');

try {
  fs.writeFileSync('cookbook.html', html);
} catch (err) {
  console.error(err);
}
