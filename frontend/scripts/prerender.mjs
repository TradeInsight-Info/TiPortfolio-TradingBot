/**
 * Prerender script — run after `vite build` and the SSR build.
 *
 * 1. Imports the SSR bundle (dist-server/entry-server.js)
 * 2. Calls render() to get the HTML string
 * 3. Injects it into dist/index.html so crawlers get real content
 * 4. Cleans up the temporary SSR build artefacts (dist-server/)
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const distDir    = path.resolve(__dirname, '../dist')
const serverDir  = path.resolve(__dirname, '../dist-server')

const template = fs.readFileSync(path.join(distDir, 'index.html'), 'utf-8')

const { render } = await import(path.join(serverDir, 'entry-server.js'))
const appHtml = render()

const html = template.replace(
  '<div id="root"></div>',
  `<div id="root">${appHtml}</div>`,
)

fs.writeFileSync(path.join(distDir, 'index.html'), html)
fs.rmSync(serverDir, { recursive: true, force: true })

console.log('✓ Prerendered index.html written to dist/')
