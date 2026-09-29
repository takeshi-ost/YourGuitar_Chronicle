// Expand only page-owned assets for existing DOM/renderer unit tests.
// Shared dependencies remain explicit script links and are tested separately.
const fs = require('node:fs');
const path = require('node:path');
module.exports = filename => fs.readFileSync(filename, 'utf8')
  .replace(/<link rel="stylesheet" href="\/assets\/pages\/([\w-]+\.css)">/g,
    (_, asset) => '<style>' + fs.readFileSync(path.join(path.dirname(filename), 'pages', asset), 'utf8') + '</style>')
  .replace(/<script src="\/assets\/pages\/([\w-]+\.js)" defer><\/script>/g,
    (_, asset) => '<script>' + fs.readFileSync(path.join(path.dirname(filename), 'pages', asset), 'utf8') + '</script>');
